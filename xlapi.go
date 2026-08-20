package xunlei

import (
	"context"
	"encoding/json"
	"fmt"
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
	dc driveDoer // 引擎(sock) 客户端
}

type driveDoer interface {
	Do(context.Context, string, string, string, any, any) (*drive.Result, error)
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

// writeDriveFailure 保留引擎原始错误体，同时确保调用方能通过 HTTP 状态识别失败。
func writeDriveFailure(w http.ResponseWriter, res *drive.Result) bool {
	if res == nil || (res.Status < http.StatusBadRequest && res.Error() == "") {
		return false
	}
	status := res.Status
	if status < http.StatusBadRequest {
		status = http.StatusBadGateway
	}
	writeJSON(w, status, res.Raw())
	return true
}

func mustJSON(v any) []byte {
	b, _ := json.Marshal(v)
	return b
}

// magnetDisplayName 从磁力链接的 dn= 参数提取显示名。
func magnetDisplayName(u string) string {
	_, after, ok := strings.Cut(u, "dn=")
	if !ok {
		return ""
	}
	if i := strings.IndexByte(after, '&'); i >= 0 {
		after = after[:i]
	}
	if dec, err := url.QueryUnescape(after); err == nil {
		return dec
	}
	return after
}

type driveFolder struct {
	ID       string `json:"id"`
	ParentID string `json:"parent_id"`
	Name     string `json:"name"`
	Params   struct {
		AliasPath string `json:"AliasPath"`
		RealPath  string `json:"RealPath"`
	} `json:"params"`
}

func normalizedFolderPath(p string) string {
	if strings.TrimSpace(p) == "" {
		return ""
	}
	return strings.TrimRight(path.Clean(p), "/") + "/"
}

func folderRealPath(folder driveFolder) string {
	if p := normalizedFolderPath(folder.Params.RealPath); p != "" {
		return p
	}
	return normalizedFolderPath(folder.Params.AliasPath)
}

// driveFolders 与面板的目录选择器一致，通过 drive/v1/files 获取目录身份。
// device/v1/vfs 返回的是挂载身份，不能作为下载任务的 parent_folder_id。
func (a *XLAPI) driveFolders(ctx context.Context, space, parentID string) ([]driveFolder, error) {
	filters, _ := json.Marshal(map[string]any{"kind": map[string]string{"eq": "drive#folder"}})
	q := url.Values{}
	q.Set("space", space)
	q.Set("limit", "200")
	q.Set("parent_id", parentID)
	q.Set("filters", string(filters))
	q.Set("page_token", "")
	q.Add("with", "withCategoryDiskMountPath")
	q.Add("with", "withCategoryDownloadPath")

	var out struct {
		Files []driveFolder `json:"files"`
	}
	res, err := a.dc.Do(ctx, http.MethodGet, "/drive/v1/files?"+q.Encode(), "", nil, &out)
	if err != nil {
		return nil, err
	}
	if res.Status != http.StatusOK || res.Error() != "" {
		return nil, fmt.Errorf("迅雷目录查询失败: %s", resErr(res))
	}
	return out.Files, nil
}

// vfsFolder 探测设备本地下载根目录: 返回面板使用的 (drive 目录 id, 路径)。
// parent_folder_id/path 是任务真正开始下载的必要字段。
func (a *XLAPI) vfsFolder(ctx context.Context, space string) (id, folderPath string, err error) {
	var cfg struct {
		DownloadPaths []string `json:"download_paths"`
	}
	if _, callErr := a.dc.Do(ctx, http.MethodGet, "/device/config", "", nil, &cfg); callErr == nil && len(cfg.DownloadPaths) > 0 {
		folderPath = normalizedFolderPath(cfg.DownloadPaths[0])
	}
	if folderPath == "" {
		return "", "", fmt.Errorf("迅雷未返回有效下载目录")
	}

	folders, err := a.driveFolders(ctx, space, "")
	if err != nil {
		return "", "", err
	}
	for _, folder := range folders {
		if folderRealPath(folder) == folderPath {
			return folder.ID, folderPath, nil
		}
	}
	return "", "", fmt.Errorf("迅雷目录索引中未找到下载根目录 %s", folderPath)
}

// descendantFolderID 按页面目录树逐级解析目标路径对应的 drive folder id。
func (a *XLAPI) descendantFolderID(ctx context.Context, space, rootID, rootPath, dest string) (string, error) {
	root := strings.TrimRight(normalizedFolderPath(rootPath), "/")
	target := strings.TrimRight(normalizedFolderPath(dest), "/")
	if target == root {
		return rootID, nil
	}
	rel := strings.TrimPrefix(target, root+"/")
	parentID, currentPath := rootID, root
	for _, segment := range strings.Split(rel, "/") {
		currentPath += "/" + segment
		folders, err := a.driveFolders(ctx, space, parentID)
		if err != nil {
			return "", err
		}
		found := false
		for _, folder := range folders {
			if strings.TrimRight(folderRealPath(folder), "/") == currentPath || folder.Name == segment {
				parentID = folder.ID
				found = true
				break
			}
		}
		if !found {
			return "", fmt.Errorf("迅雷目录索引中未找到 %s，请先在 dirs 中确认目录", currentPath)
		}
	}
	return parentID, nil
}

type taskMeta struct {
	Space  string `json:"space"`
	Type   string `json:"type"`
	Params struct {
		URL string `json:"url"`
	} `json:"params"`
}

// taskOf 按 id 查任务真实的 space/type/url。
func (a *XLAPI) taskOf(ctx context.Context, space, id string) (taskMeta, *drive.Result, error) {
	space = strings.TrimSpace(space)
	if space == "" {
		var err error
		space, err = a.deviceSpace(ctx)
		if err != nil {
			return taskMeta{}, nil, err
		}
	}
	f := map[string]any{"id": map[string]any{"in": id}}
	fj, _ := json.Marshal(f)
	p := "/drive/v1/tasks?" + drive.Query("space", space, "filters", string(fj))
	var out struct {
		Tasks []taskMeta `json:"tasks"`
	}
	// space 是任务查询条件；Device-Space/device_space 与当前面板一样保持空值。
	res, err := a.dc.Do(ctx, http.MethodGet, p, "", nil, &out)
	if err != nil || res.Status != http.StatusOK || len(out.Tasks) == 0 {
		return taskMeta{}, res, err
	}
	return out.Tasks[0], res, nil
}

// deviceSpace 从当前运行中的 user#runner 任务读取设备空间。
// 迅雷面板使用 runner.params.target，而 /device/config.device_space 通常为空。
func (a *XLAPI) deviceSpace(ctx context.Context) (string, error) {
	var runners struct {
		Tasks []struct {
			Params struct {
				Target string `json:"target"`
			} `json:"params"`
		} `json:"tasks"`
	}
	p := "/drive/v1/tasks?" + drive.Query("type", "user#runner")
	res, err := a.dc.Do(ctx, http.MethodGet, p, "", nil, &runners)
	if err != nil {
		return "", err
	}
	if res.Status == http.StatusOK {
		for _, runner := range runners.Tasks {
			if target := strings.TrimSpace(runner.Params.Target); target != "" {
				return target, nil
			}
		}
	}

	// 兼容少数会直接返回 device_space 的旧引擎。
	var cfg struct {
		DeviceSpace string `json:"device_space"`
	}
	if res, err := a.dc.Do(ctx, http.MethodGet, "/device/config", "", nil, &cfg); err == nil && res.Status == 200 && cfg.DeviceSpace != "" {
		return cfg.DeviceSpace, nil
	}
	return "", fmt.Errorf("当前迅雷设备空间未激活")
}

type parsedResource struct {
	Name      string `json:"name"`
	FileName  string `json:"file_name"`
	FileSize  any    `json:"file_size"`
	FileCount any    `json:"file_count"`
	MimeType  string `json:"mime_type"`
	FileID    string `json:"file_id"`
}

type resourceList struct {
	ListID string `json:"list_id"`
	List   struct {
		Resources []parsedResource `json:"resources"`
	} `json:"list"`
}

// parseDownload 与迅雷面板一致，先解析 URL/磁力，再用解析结果创建任务。
func (a *XLAPI) parseDownload(ctx context.Context, rawURL string) (*drive.Result, resourceList, error) {
	var parsed resourceList
	res, err := a.dc.Do(ctx, http.MethodPost, "/drive/v1/resource/list", "", map[string]any{
		"page_size": 2000,
		"urls":      rawURL,
	}, &parsed)
	return res, parsed, err
}

func scalarString(v any, fallback string) string {
	var s string
	switch x := v.(type) {
	case string:
		s = x
	case float64:
		s = strconv.FormatFloat(x, 'f', -1, 64)
	case json.Number:
		s = x.String()
	case nil:
	default:
		s = fmt.Sprint(x)
	}
	if strings.TrimSpace(s) == "" {
		return fallback
	}
	return s
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

	space := strings.TrimSpace(req.Space)
	if space == "" {
		var err error
		space, err = a.deviceSpace(r.Context())
		if err != nil {
			a.err(w, http.StatusServiceUnavailable, "获取当前迅雷设备空间失败: "+err.Error())
			return
		}
	}

	parseRes, parsed, err := a.parseDownload(r.Context(), req.URL)
	if err != nil {
		a.err(w, http.StatusBadGateway, "解析下载链接失败: "+err.Error())
		return
	}
	if writeDriveFailure(w, parseRes) {
		return
	}
	if len(parsed.List.Resources) == 0 {
		a.err(w, http.StatusUnprocessableEntity, "迅雷未解析出可下载资源")
		return
	}
	resource := parsed.List.Resources[0]

	name := strings.TrimSpace(req.Name)
	if name == "" {
		name = strings.TrimSpace(resource.Name)
	}
	if name == "" {
		name = strings.TrimSpace(resource.FileName)
	}
	if name == "" {
		switch {
		case strings.HasPrefix(req.URL, "magnet:"), strings.HasPrefix(req.URL, "bt:"), strings.HasPrefix(req.URL, "ed2k:"):
			name = magnetDisplayName(req.URL)
		default:
			if u, e := url.Parse(req.URL); e == nil && u.Path != "" {
				name = path.Base(u.Path)
			}
		}
	}
	if name == "" || name == "." || name == "/" {
		name = "unnamed"
	}

	// 目标目录: 用户指定 path(完整) > dir(下载根下的相对目录, 如 "电影/动漫") > 下载根目录。
	// parent_folder_id/path 是关键字段, 缺省任务不会开始下载。
	pfid, rootPath, err := a.vfsFolder(r.Context(), space)
	if err != nil {
		a.err(w, http.StatusServiceUnavailable, "获取下载目录失败: "+err.Error())
		return
	}

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
		pfid, err = a.descendantFolderID(r.Context(), space, pfid, rootPath, dest)
		if err != nil {
			a.err(w, http.StatusUnprocessableEntity, "获取目标目录失败: "+err.Error())
			return
		}
	}

	body := map[string]any{
		"type":      "user#download-url",
		"name":      name,
		"file_name": name,
		"file_size": scalarString(resource.FileSize, "0"),
		"space":     space,
		"params": map[string]any{
			"target":             space,
			"url":                req.URL,
			"total_file_count":   scalarString(resource.FileCount, "1"),
			"parent_folder_path": pfpath,
			"parent_folder_id":   pfid,
			"sub_file_index":     "--1,",
			"mime_type":          resource.MimeType,
			"file_id":            resource.FileID,
		},
	}

	// 当前面板只在 body 中传 space/target，传输层 Device-Space/device_space 保持空值。
	res, err := a.dc.Do(r.Context(), http.MethodPost, "/drive/v1/task", "", body, nil)
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+err.Error())
		return
	}

	if writeDriveFailure(w, res) {
		return
	}

	writeJSON(w, res.Status, res.Raw())
}

// listTasks GET /api/v1/tasks?all=1&page_token=&limit=
func (a *XLAPI) listTasks(w http.ResponseWriter, r *http.Request) {
	space := strings.TrimSpace(r.URL.Query().Get("space"))
	if space == "" {
		var err error
		space, err = a.deviceSpace(r.Context())
		if err != nil {
			a.err(w, http.StatusServiceUnavailable, "获取当前迅雷设备空间失败: "+err.Error())
			return
		}
	}
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

	res, err := a.dc.Do(r.Context(), http.MethodGet, path, "", nil, nil)
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+err.Error())
		return
	}
	if writeDriveFailure(w, res) {
		return
	}
	writeJSON(w, res.Status, res.Raw())
}

// taskFiles GET /api/v1/tasks/{id}/files
// 获取该任务解析出的下载文件列表(磁力/种子文件树)。
// 对应页面新增下载时「获取磁力详细文件信息」那一步, 返回 list.resources。
func (a *XLAPI) taskFiles(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	task, res, err := a.taskOf(r.Context(), strings.TrimSpace(r.URL.Query().Get("space")), id)
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+err.Error())
		return
	}
	if writeDriveFailure(w, res) {
		return
	}
	if task.Type == "" {
		a.err(w, http.StatusNotFound, "task not found")
		return
	}
	if strings.TrimSpace(task.Params.URL) == "" {
		a.err(w, http.StatusUnprocessableEntity, "task has no downloadable url")
		return
	}
	res, _, err = a.parseDownload(r.Context(), task.Params.URL)
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+err.Error())
		return
	}
	if writeDriveFailure(w, res) {
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

	requestedSpace := strings.TrimSpace(r.URL.Query().Get("space"))
	task, lookupRes, lookupErr := a.taskOf(r.Context(), requestedSpace, id)
	if lookupErr != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+lookupErr.Error())
		return
	}
	if writeDriveFailure(w, lookupRes) {
		return
	}
	if task.Type == "" {
		a.err(w, http.StatusNotFound, "task not found")
		return
	}
	space, typ := task.Space, task.Type

	var err error
	var res *drive.Result
	action := strings.ToLower(strings.TrimSpace(req.Action))
	switch action {
	case "pause", "stop", "resume", "running":
		phase := "pause"
		if action == "resume" || action == "running" {
			phase = "running"
		}
		body := map[string]any{
			"space": space, "type": typ, "id": id,
			"set_params": map[string]any{"spec": string(mustJSON(map[string]string{"phase": phase}))},
		}
		res, err = a.dc.Do(r.Context(), http.MethodPatch, "/drive/v1/task", "", body, nil)
	case "delete":
		p := "/drive/v1/tasks?" + drive.Query("space", space, "task_ids", id)
		res, err = a.dc.Do(r.Context(), http.MethodDelete, p, "", nil, nil)
	default:
		a.err(w, http.StatusBadRequest, "action 必须是 pause/resume/delete")
		return
	}
	if err != nil {
		a.err(w, http.StatusBadGateway, "drive call fail: "+err.Error())
		return
	}
	if writeDriveFailure(w, res) {
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
