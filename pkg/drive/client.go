// Package drive 提供与迅雷 pan-cli 引擎(主程序)的本地 HTTP 通信。
//
// 引擎在主程序 unix socket (SOCK_DRIVE_LISTEN) 上提供 REST 风格 HTTP 接口。
// 所有受保护接口都需要在 pan-auth 头(或 pan_auth 查询参数)中携带引擎签发的
// UIAuth JWT —— 该 token 由引擎注入到其自身托管页面(index.html)的
// "function uiauth()..." 脚本中, 通过抓取该页面即可获得。
package drive

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
)

var uiauthRe = regexp.MustCompile(`function\s+uiauth\s*\(\s*\w*\s*\)\s*\{\s*return\s*"([^"]+)"\s*\}`)

// Client 是连接引擎 unix socket 的 HTTP 客户端, 自动维护 pan-auth token。
type Client struct {
	sock string // unix socket 路径 (chroot 视角)
	hc   *http.Client

	mu     sync.Mutex
	tok    string
	tokExp time.Time
}

// New 创建一个指向 sock (unix socket 路径) 的客户端。
func New(sock string) *Client {
	return &Client{
		sock: sock,
		hc: &http.Client{
			Timeout: 30 * time.Second,
			Transport: &http.Transport{
				DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
					var d net.Dialer
					return d.DialContext(ctx, "unix", sock)
				},
			},
		},
	}
}

// token 获取/刷新 pan-auth JWT。
func (c *Client) token(ctx context.Context) (string, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.tok != "" && time.Now().Before(c.tokExp) {
		return c.tok, nil
	}

	nw, err := c.fetchToken(ctx)
	if err != nil {
		// token 过期但还能用旧的时, 不阻塞调用
		if c.tok != "" {
			slog.DebugContext(ctx, "drive: refresh uiauth token fail, use cached", "err", err)
			return c.tok, nil
		}
		return "", err
	}

	c.tok = nw
	c.tokExp = time.Now().Add(6 * time.Hour)
	slog.DebugContext(ctx, "drive: uiauth token refreshed", "len", len(nw))
	return nw, nil
}

// fetchToken 从引擎自身托管的页面中提取 uiauth JWT。
func (c *Client) fetchToken(ctx context.Context) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://localhost/", nil)
	if err != nil {
		return "", err
	}
	resp, err := c.hc.Do(req)
	if err != nil {
		return "", fmt.Errorf("drive: fetch home page: %w", err)
	}
	defer resp.Body.Close()

	b, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if err != nil {
		return "", fmt.Errorf("drive: read home page: %w", err)
	}
	m := uiauthRe.FindSubmatch(b)
	if len(m) != 2 || len(m[1]) == 0 {
		return "", fmt.Errorf("drive: uiauth token not found in home page")
	}
	return string(m[1]), nil
}

// Result 保留引擎返回的原始 JSON, 便于透传与调试。
type Result struct {
	Status int             // HTTP 状态码
	Body   json.RawMessage // 原始响应体
}

// Raw 把 Result 解码到 out; 若引擎返回错误字段, 一并给出。
func (r *Result) Raw() json.RawMessage { return r.Body }

// Error 返回引擎错误信息(优先 error_description / error), 无则空。
func (r *Result) Error() string {
	if len(r.Body) == 0 {
		return ""
	}
	var e struct {
		Error            string `json:"error"`
		ErrorDescription string `json:"error_description"`
		HttpStatus       int    `json:"HttpStatus"`
	}
	if err := json.Unmarshal(r.Body, &e); err == nil {
		msg := strings.TrimSpace(e.ErrorDescription)
		if msg == "" {
			msg = strings.TrimSpace(e.Error)
		}
		return msg
	}
	return ""
}

// Do 发起一次对引擎的请求, space 会同时写入 Device-Space 头与 pan_auth/device_space 查询参数。
func (c *Client) Do(ctx context.Context, method, path string, space string, body any, out any) (*Result, error) {
	tok, err := c.token(ctx)
	if err != nil {
		return nil, err
	}

	var bodyBytes []byte
	if body != nil {
		bodyBytes, err = json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("drive: marshal body: %w", err)
		}
	}

	do := func(auth string) (*Result, error) {
		var rd io.Reader
		if bodyBytes != nil {
			rd = bytes.NewReader(bodyBytes)
		}
		req, e := http.NewRequestWithContext(ctx, method, "http://localhost"+path, rd)
		if e != nil {
			return nil, e
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("pan-auth", auth)
		req.Header.Set("Device-Space", space)
		if q := req.URL.Query(); space != "" {
			q.Set("device_space", space)
			req.URL.RawQuery = q.Encode()
		}

		resp, e := c.hc.Do(req)
		if e != nil {
			return nil, fmt.Errorf("drive: %s %s: %w", method, path, e)
		}
		defer resp.Body.Close()
		b, e := io.ReadAll(io.LimitReader(resp.Body, 32<<20))
		if e != nil {
			return nil, fmt.Errorf("drive: read resp: %w", e)
		}
		return &Result{Status: resp.StatusCode, Body: b}, nil
	}

	r, err := do(tok)
	if err != nil {
		return nil, err
	}

	// 仅当是 uiauth token 校验失败(403 checkAuth/permission_deny)时才刷新并重试;
	// 401 通常是账户未登录(refresh token not found), 重试无意义且会翻倍延迟。
	if r.Status == http.StatusForbidden && strings.Contains(string(r.Body), "checkAuth") {
		c.mu.Lock()
		c.tok = ""
		c.mu.Unlock()
		if tok2, e := c.token(ctx); e == nil && tok2 != "" {
			if retried, e2 := do(tok2); e2 == nil {
				r = retried
			}
		}
	}
	if out != nil && len(r.Body) > 0 {
		if err := json.Unmarshal(r.Body, out); err != nil {
			slog.DebugContext(ctx, "drive: unmarshal resp fail", "path", path, "body", truncate(r.Body, 512))
		}
	}

	return r, nil
}

func truncate(b []byte, n int) string {
	if len(b) > n {
		return string(b[:n]) + "..."
	}
	return string(b)
}

// Query 构造查询参数。
func Query(kv ...string) string {
	u := &url.Values{}
	if len(kv)%2 != 0 {
		panic("drive: Query expects even args")
	}
	for i := 0; i < len(kv); i += 2 {
		u.Set(kv[i], kv[i+1])
	}
	return u.Encode()
}
