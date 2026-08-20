package drive

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) { return f(req) }

func response(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader(body)),
	}
}

func TestDoReplaysBodyAfterUIAuthRefresh(t *testing.T) {
	const wantBody = `{"urls":"magnet:?xt=urn:btih:test"}`
	requestCount := 0
	client := &Client{tok: "old-token", tokExp: time.Now().Add(time.Hour)}
	client.hc = &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
		switch req.URL.Path {
		case "/drive/v1/resource/list":
			requestCount++
			body, err := io.ReadAll(req.Body)
			if err != nil {
				t.Fatalf("read request body: %v", err)
			}
			if string(body) != wantBody {
				t.Fatalf("request %d body = %q, want %q", requestCount, body, wantBody)
			}
			if requestCount == 1 {
				if req.Header.Get("pan-auth") != "old-token" {
					t.Fatalf("first token = %q", req.Header.Get("pan-auth"))
				}
				return response(http.StatusForbidden, `{"error":"checkAuth permission_deny"}`), nil
			}
			if req.Header.Get("pan-auth") != "new-token" {
				t.Fatalf("retried token = %q", req.Header.Get("pan-auth"))
			}
			return response(http.StatusOK, `{"ok":true}`), nil
		case "/":
			return response(http.StatusOK, `<script>function uiauth(){ return "new-token" }</script>`), nil
		default:
			t.Fatalf("unexpected request path %q", req.URL.Path)
			return nil, nil
		}
	})}

	var out map[string]any
	res, err := client.Do(context.Background(), http.MethodPost, "/drive/v1/resource/list", "", map[string]string{
		"urls": "magnet:?xt=urn:btih:test",
	}, &out)
	if err != nil {
		t.Fatalf("Do: %v", err)
	}
	if res.Status != http.StatusOK || out["ok"] != true || requestCount != 2 {
		t.Fatalf("result = %#v, out = %#v, requests = %d", res, out, requestCount)
	}
}
