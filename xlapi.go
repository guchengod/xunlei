package xunlei

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"path"
	"sort"
	"strconv"
	"strings"

	"github.com/cnk3x/xunlei/pkg/drive"
	"github.com/go-chi/chi/v5"
)

type XLAPI struct {
	dc *drive.Client // 引擎(sock) 客户端
}

// NewAPI 创建对外 API。sock 为引擎主程序 unix socket 路径(chroot 视角)。
func NewAPI(sock string) *XLAPI {
	return &XLAPI{dc: drive.New(sock)}
}

// Mount 注册 /api/v1 路由。
func (a *XLAPI) Mount(r chi.Router) {
	r.Get("/info", a.info)
	r.Post("/download", a.addDownload)
	r.Get("/dirs", a.dirs)
	r.Get("/tasks", a.listTasks)
	r.Get("/tasks/{id}/files", a.taskFiles)
	r.Post("/tasks/{id}/action", a.taskAction)
	r.Get("/login", a.loginState)
}

// writeJSON 原样透传引擎响应。
func writeJSON(w http.ResponseWriter, status int, body []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	w.Write(body)
}

func (a *XLAPI) err(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, mustJSON(map[string]any{"error": msg, "success": false}))
}

func mustJSON(v any) []byte {
	b, _ := json.Marshal(v)
	return b
}

// spaceOf: 仅当调用方显式传入 space 时才使用; 否则留空, 由引擎按设备空间解析。
// 注意: 不要回填 device_id# 空间 —— 设备空间未激活时会触发 device_space_not_active,
// 空 space 引擎反而能正确解析(实测)。创建任务后置 running 用创建响应里的 task.space。
func (a *XLAPI) spaceOf(space string) string {
	return space
}

// vfsFolder 探测设备本地下载根目录: 返回 (目录id, 路径)。
// parent_folder_id/path 是任务真正开始下载的必要字段。
func (a *XLAPI) vfsFolder(ctx context.Context) (id, path string) {
	var cfg struct {
		DownloadPaths []string `json:"download_paths"`
	}
	if _, err := a.dc.Do(ctx, http.MethodGet, "/device/config", "", nil, &cfg); err == nil && len(cfg.DownloadPaths) > 0 {
		path = strings.TrimRight(cfg.DownloadPaths[0], "/") + "/"
	}
	var vfs struct {
		List []struct {
			FileID string `json:"file_id"`
		} `json:"vfs_list"`
	}
	if _, err := a.dc.Do(ctx, http.MethodGet, "/device/v1/vfs", "", nil, &vfs); err == nil && len(vfs.List) > 0 {
		id = vfs.List[0].FileID
	}
	return
}

// taskTypeOf 按 id 查任务的 type (PATCH 操作用)。
func (a *XLAPI) taskTypeOf(ctx context.Context, space, id string) string {
	f := map[string]any{"id": map[string]any{"in": id}}
	fj, _ := json.Marshal(f)
	p := "/drive/v1/tasks?" + drive.Query("space", space, "filters", string(fj))
	var out struct {
		Tasks []struct {
			Type string `json:"type"`
		} `json:"tasks"`
	}
	if res, err := a.dc.Do(ctx, http.MethodGet, p, space, nil, &out); err == nil && res.Status == 200 && len(out.Tasks) > 0 {
		return out.Tasks[0].Type
	}
	return "user#download-url"
}

// info GET /api/v1/info
// 返回设备配置、登录态、下载目录、运行版本等。
func (a *XLAPI) info(w http.ResponseWriter, r *http.Request) {
	m := map[string]any{}

	var cfg json.RawMessage
	res, err := a.dc.Do(r.Context(), http.MethodGet, "/device/config", "", nil, &cfg)
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive unreachable: "+err.Error())
		return
	}
	m["device"] = json.RawMessage(res.Raw())
	if cfg != nil {
		m["device"] = cfg
	}

	// 任务列表类型过滤用空间
	m["login"] = map[string]any{
		"logged_in": false,
		"message":   "未登录",
	}

	var about json.RawMessage
	if rab, err := a.dc.Do(r.Context(), http.MethodGet, "/drive/v1/about", "", nil, &about); err == nil && rab.Raw() != nil && rab.Status == 200 {
		m["login"] = map[string]any{
			"logged_in": true,
			"message":   "已登录",
		}
		m["user"] = json.RawMessage(rab.Raw())
	} else {
		m["login"] = map[string]any{
			"logged_in": false,
			"message":   resErr(rab),
		}
	}

	writeJSON(w, http.StatusOK, mustJSON(m))
}

func resErr(r *drive.Result) string {
	if r != nil {
		if msg := r.Error(); msg != "" {
			return msg
		}
	}
	return "未登录"
}

// downloadRoots 返回设备本地下载根目录列表 (来自引擎 device/config, chroot 视角路径)。
func (a *XLAPI) downloadRoots(ctx context.Context) []string {
	var cfg struct {
		DownloadPaths []string `json:"download_paths"`
	}
	if res, err := a.dc.Do(ctx, http.MethodGet, "/device/config", "", nil, &cfg); err == nil && res.Status == 200 && len(cfg.DownloadPaths) > 0 {
		return cfg.DownloadPaths
	}
	return []string{"/downloads/"}
}

type dirNode struct {
	Name string    `json:"name"`
	Path string    `json:"path"`
	Dirs []dirNode `json:"dirs,omitempty"`
}

// dirs GET /api/v1/dirs — 列出设备本地可下载目录树(供选择保存位置)。
// 由 xlp 直接扫描 chroot 内下载根目录得到, 与引擎/面板挂载的目录一致。
func (a *XLAPI) dirs(w http.ResponseWriter, r *http.Request) {
	roots := make([]dirNode, 0, 2)
	for _, root := range a.downloadRoots(r.Context()) {
		rootPath := strings.TrimRight(root, "/")
		if rootPath == "" {
			continue
		}
		roots = append(roots, dirNode{
			Name: path.Base(rootPath),
			Path: rootPath + "/",
			Dirs: scanDirTree(rootPath, 0, 2),
		})
	}
	writeJSON(w, http.StatusOK, mustJSON(map[string]any{"roots": roots}))
}

// scanDirTree 递归列出目录(最多 maxDepth 层), 每个节点带 name/path 与子目录。
func scanDirTree(dirPath string, depth, maxDepth int) []dirNode {
	if depth >= maxDepth {
		return nil
	}
	entries, err := os.ReadDir(dirPath)
	if err != nil {
		return nil
	}
	nodes := make([]dirNode, 0, len(entries))
	for _, e := range entries {
		if !e.IsDir() || strings.HasPrefix(e.Name(), ".") {
			continue
		}
		p := path.Join(dirPath, e.Name())
		nodes = append(nodes, dirNode{
			Name: e.Name(),
			Path: p,
			Dirs: scanDirTree(p, depth+1, maxDepth),
		})
	}
	sort.Slice(nodes, func(i, j int) bool { return nodes[i].Name < nodes[j].Name })
	return nodes
}

// addDownload POST /api/v1/download
// body: {"url":"...","name":"...(可选)","space":"...(可选)",
//
//	"path":"/downloads/电影(可选, 完整目录)","dir":"电影/动漫(可选, 下载根下的相对目录)"}
func (a *XLAPI) addDownload(w http.ResponseWriter, r *http.Request) {
	var req struct {
		URL   string `json:"url"`
		Name  string `json:"name"`
		Path  string `json:"path"`
		Dir   string `json:"dir"`
		Space string `json:"space"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		a.err(w, http.StatusBadRequest, "json decode: "+err.Error())
		return
	}
	if strings.TrimSpace(req.URL) == "" {
		a.err(w, http.StatusBadRequest, "url 不能为空")
		return
	}
	if !strings.HasPrefix(req.URL, "http") && !strings.HasPrefix(req.URL, "magnet") &&
		!strings.HasPrefix(req.URL, "thunder") && !strings.HasPrefix(req.URL, "ftp") &&
		!strings.HasPrefix(req.URL, "ed2k") && !strings.HasPrefix(req.URL, "emule") &&
		!strings.HasPrefix(req.URL, "bt:") && !strings.HasPrefix(req.URL, "file:") {
		a.err(w, http.StatusBadRequest, "不支持的任务链接: "+req.URL)
		return
	}

	space := a.spaceOf(req.Space)

	name := strings.TrimSpace(req.Name)
	if name == "" {
		if u, e := url.Parse(req.URL); e == nil && u.Path != "" {
			name = path.Base(u.Path)
		}
	}
	if name == "" || name == "." || name == "/" {
		name = "download"
	}

	// 目标目录: 用户指定 path(完整) > dir(下载根下的相对目录, 如 "电影/动漫") > 下载根目录。
	// parent_folder_id/path 是关键字段, 缺省任务不会开始下载。
	pfid, rootPath := a.vfsFolder(r.Context())

	dest := strings.TrimSpace(req.Path)
	if dest == "" && strings.TrimSpace(req.Dir) != "" {
		dest = path.Join(strings.TrimRight(rootPath, "/"), strings.TrimSpace(req.Dir))
	}
	// 防目录穿越: 确保 dest 落在下载根目录内
	if dest != "" {
		clean := path.Clean(dest)
		root := path.Clean(rootPath)
		if clean != root && !strings.HasPrefix(clean, root+"/") {
			a.err(w, http.StatusBadRequest, "目录越界: "+dest)
			return
		}
		dest = clean
	}
	pfpath := rootPath
	if dest != "" {
		pfpath = strings.TrimRight(dest, "/") + "/"
	}

	body := map[string]any{
		"type":      "user#download-url",
		"name":      name,
		"file_name": name,
		"file_size": "0",
		"space":     space,
		"params": map[string]any{
			"target":             space,
			"url":                req.URL,
			"total_file_count":   "1",
			"parent_folder_path": pfpath,
			"parent_folder_id":   pfid,
			"mime_type":          "",
			"file_id":            "",
		},
	}

	res, err := a.dc.Do(r.Context(), http.MethodPost, "/drive/v1/task", space, body, nil)
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+err.Error())
		return
	}

	if e := res.Error(); e != "" && res.Status != 200 {
		a.err(w, http.StatusOK, e)
		return
	}

	// 创建成功: 自动开始下载 (面板流程也是创建后立即置 running)
	var created struct {
		Task struct {
			ID    string `json:"id"`
			Space string `json:"space"`
			Phase string `json:"phase"`
		} `json:"task"`
	}
	_ = json.Unmarshal(res.Raw(), &created)
	if created.Task.ID != "" && created.Task.Phase != "PHASE_TYPE_RUNNING" {
		// 置 running 用创建响应回填的 device space (device_id#...)
		sp := created.Task.Space
		if sp == "" {
			sp = space
		}
		spec := []byte(`{"phase":"running"}`) // 引擎的 spec 是 bytes 字段, 会自动 base64
		act := map[string]any{
			"space": sp, "type": "user#download-url", "id": created.Task.ID,
			"set_params": map[string]any{"spec": spec},
		}
		if ra, e := a.dc.Do(r.Context(), http.MethodPatch, "/drive/v1/task", sp, act, nil); e == nil {
			slog.DebugContext(r.Context(), "api: auto start task", "id", created.Task.ID, "code", ra.Status)
		}
	}

	writeJSON(w, res.Status, res.Raw())
}

// listTasks GET /api/v1/tasks?all=1&page_token=&limit=
func (a *XLAPI) listTasks(w http.ResponseWriter, r *http.Request) {
	// 不强制 space: 引擎默认解析到设备空间
	space := a.spaceOf(r.URL.Query().Get("space"))
	limit := r.URL.Query().Get("limit")
	if limit == "" {
		limit = "100"
	}
	if _, e := strconv.Atoi(limit); e != nil {
		a.err(w, http.StatusBadRequest, "limit 必须是数字")
		return
	}
	filters := map[string]any{"type": map[string]any{"in": "user#download,user#download-url"}}
	if r.URL.Query().Get("all") == "" {
		filters["phase"] = map[string]any{"in": "PHASE_TYPE_PENDING,PHASE_TYPE_RUNNING"}
	}
	fj, _ := json.Marshal(filters)

	path := "/drive/v1/tasks?" + drive.Query(
		"space", space,
		"page_token", r.URL.Query().Get("page_token"),
		"filters", string(fj),
		"limit", limit,
	)

	res, err := a.dc.Do(r.Context(), http.MethodGet, path, space, nil, nil)
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+err.Error())
		return
	}
	writeJSON(w, res.Status, res.Raw())
}

// taskFiles GET /api/v1/tasks/{id}/files
// 获取该任务解析出的下载文件列表(磁力/种子文件树)。
// 对应页面新增下载时「获取磁力详细文件信息」那一步, 返回 list.resources。
func (a *XLAPI) taskFiles(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	space := a.spaceOf(r.URL.Query().Get("space"))
	typ := a.taskTypeOf(r.Context(), space, id)
	body := map[string]any{"space": space, "id": id, "type": typ}
	res, err := a.dc.Do(r.Context(), http.MethodPost, "/drive/v1/resource/list", space, body, nil)
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+err.Error())
		return
	}
	writeJSON(w, res.Status, res.Raw())
}

// taskAction POST /api/v1/tasks/{id}/action
// body: {"action":"pause"|"resume"|"delete"}
func (a *XLAPI) taskAction(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	var req struct {
		Action string `json:"action"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		a.err(w, http.StatusBadRequest, "json decode: "+err.Error())
		return
	}

	// 操作目标空间: 显式 / 最近创建任务 / 空(引擎默认) 均可
	space := a.spaceOf(r.URL.Query().Get("space"))
	// 任务的真实 type (PATCH 需要, 否则引擎不认)
	typ := a.taskTypeOf(r.Context(), space, id)

	var err error
	var res *drive.Result
	switch strings.ToLower(req.Action) {
	case "pause", "running", "stop":
		phase := "pause"
		if req.Action == "running" {
			phase = "running"
		}
		body := map[string]any{
			"space": space, "type": typ, "id": id,
			"set_params": map[string]any{"spec": mustJSON(map[string]string{"phase": phase})},
		}
		res, err = a.dc.Do(r.Context(), http.MethodPatch, "/drive/v1/task", space, body, nil)
	case "delete":
		// 删除不传 space(实测带 space 反而报无效空间)
		p := "/drive/v1/tasks?" + drive.Query("task_ids", id)
		res, err = a.dc.Do(r.Context(), http.MethodDelete, p, space, nil, nil)
	default:
		a.err(w, http.StatusBadRequest, "action 必须是 pause/resume/delete")
		return
	}
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+err.Error())
		return
	}
	writeJSON(w, res.Status, res.Raw())
}

// loginState GET /api/v1/login
func (a *XLAPI) loginState(w http.ResponseWriter, r *http.Request) {
	var about json.RawMessage
	res, err := a.dc.Do(r.Context(), http.MethodGet, "/drive/v1/about", "", nil, &about)
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive unreachable: "+err.Error())
		return
	}
	m := map[string]any{"logged_in": res.Status == 200}
	if res.Status == 200 && about != nil {
		m["user"] = json.RawMessage(about)
	} else {
		m["message"] = resErr(res)
	}
	writeJSON(w, http.StatusOK, mustJSON(m))
}
