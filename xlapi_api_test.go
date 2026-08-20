package xunlei

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/cnk3x/xunlei/pkg/drive"
	"github.com/go-chi/chi/v5"
)

type fakeDriveCall struct {
	Method string
	Path   string
	Space  string
	Body   any
}

type fakeDrive struct {
	t       *testing.T
	calls   []fakeDriveCall
	replyTo func(fakeDriveCall) (int, string, error)
}

func (f *fakeDrive) Do(_ context.Context, method, requestPath, space string, body, out any) (*drive.Result, error) {
	f.t.Helper()
	call := fakeDriveCall{Method: method, Path: requestPath, Space: space, Body: cloneJSON(f.t, body)}
	f.calls = append(f.calls, call)
	status, raw, err := f.replyTo(call)
	if err != nil {
		return nil, err
	}
	res := &drive.Result{Status: status, Body: json.RawMessage(raw)}
	if out != nil && raw != "" {
		if err := json.Unmarshal([]byte(raw), out); err != nil {
			f.t.Fatalf("decode fake response: %v", err)
		}
	}
	return res, nil
}

func cloneJSON(t *testing.T, value any) any {
	t.Helper()
	if value == nil {
		return nil
	}
	b, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("marshal call body: %v", err)
	}
	var cloned any
	if err := json.Unmarshal(b, &cloned); err != nil {
		t.Fatalf("clone call body: %v", err)
	}
	return cloned
}

func serveAPI(t *testing.T, api *XLAPI, method, target, body string) *httptest.ResponseRecorder {
	t.Helper()
	router := chi.NewRouter()
	api.Mount(router)
	req := httptest.NewRequest(method, target, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec
}

func queryOf(t *testing.T, requestPath string) url.Values {
	t.Helper()
	u, err := url.Parse(requestPath)
	if err != nil {
		t.Fatalf("parse request path: %v", err)
	}
	return u.Query()
}

func TestAddDownloadMatchesPanelFlow(t *testing.T) {
	const magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
	fake := &fakeDrive{t: t}
	fake.replyTo = func(call fakeDriveCall) (int, string, error) {
		switch {
		case call.Method == http.MethodGet && strings.HasPrefix(call.Path, "/drive/v1/tasks?") && queryOf(t, call.Path).Get("type") == "user#runner":
			return 200, `{"tasks":[{"params":{"target":"device_id#current"}}]}`, nil
		case call.Method == http.MethodPost && call.Path == "/drive/v1/resource/list":
			return 200, `{"list_id":"parsed-list","list":{"resources":[{"name":"解析后的名称","file_size":229267682638,"file_count":211,"mime_type":"dir","file_id":"parsed-file"}]}}`, nil
		case call.Method == http.MethodGet && call.Path == "/device/config":
			return 200, `{"download_paths":["/downloads/"]}`, nil
		case call.Method == http.MethodGet && strings.HasPrefix(call.Path, "/drive/v1/files?") && queryOf(t, call.Path).Get("parent_id") == "":
			return 200, `{"files":[{"id":"folder-root","parent_id":"","name":"downloads","params":{"RealPath":"/downloads/"}}]}`, nil
		case call.Method == http.MethodGet && strings.HasPrefix(call.Path, "/drive/v1/files?") && queryOf(t, call.Path).Get("parent_id") == "folder-root":
			return 200, `{"files":[{"id":"folder-movie","parent_id":"folder-root","name":"电影","params":{"RealPath":"/downloads/电影/"}}]}`, nil
		case call.Method == http.MethodPost && call.Path == "/drive/v1/task":
			return 200, `{"task":{"id":"task-created","phase":"PHASE_TYPE_PENDING","space":"device_id#current"}}`, nil
		default:
			return 0, "", errors.New("unexpected drive call: " + call.Method + " " + call.Path)
		}
	}

	rec := serveAPI(t, &XLAPI{dc: fake}, http.MethodPost, "/download", `{"url":"`+magnet+`","dir":"电影"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}

	if len(fake.calls) != 6 {
		t.Fatalf("drive calls = %d, want 6: %#v", len(fake.calls), fake.calls)
	}
	parseCall := fake.calls[1]
	parseBody := parseCall.Body.(map[string]any)
	if parseCall.Space != "" || parseBody["urls"] != magnet || parseBody["page_size"] != float64(2000) {
		t.Fatalf("parse call = %#v", parseCall)
	}

	createCall := fake.calls[5]
	if createCall.Space != "" {
		t.Fatalf("create transport device space = %q, want panel-compatible empty value", createCall.Space)
	}
	created := createCall.Body.(map[string]any)
	if created["name"] != "解析后的名称" || created["file_name"] != "解析后的名称" || created["file_size"] != "229267682638" || created["space"] != "device_id#current" {
		t.Fatalf("create body = %#v", created)
	}
	params := created["params"].(map[string]any)
	if params["target"] != "device_id#current" || params["total_file_count"] != "211" || params["sub_file_index"] != "--1," {
		t.Fatalf("create params = %#v", params)
	}
	if params["parent_folder_id"] != "folder-movie" || params["parent_folder_path"] != "/downloads/电影/" {
		t.Fatalf("create destination = %#v", params)
	}
	for _, call := range fake.calls {
		if call.Method == http.MethodPatch {
			t.Fatalf("panel flow must not send an extra PATCH: %#v", call)
		}
	}
}

func TestAddDownloadPropagatesParseError(t *testing.T) {
	fake := &fakeDrive{t: t}
	fake.replyTo = func(call fakeDriveCall) (int, string, error) {
		if call.Method == http.MethodGet && strings.HasPrefix(call.Path, "/drive/v1/tasks?") {
			return 200, `{"tasks":[{"params":{"target":"device_id#current"}}]}`, nil
		}
		if call.Method == http.MethodPost && call.Path == "/drive/v1/resource/list" {
			return 200, `{"error":"refresh token not found","error_description":"未登录"}`, nil
		}
		return 0, "", errors.New("unexpected drive call")
	}

	rec := serveAPI(t, &XLAPI{dc: fake}, http.MethodPost, "/download", `{"url":"magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"}`)
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "refresh token not found") {
		t.Fatalf("engine error was not preserved: %s", rec.Body.String())
	}
	if len(fake.calls) != 2 {
		t.Fatalf("drive calls = %d, want parse to stop creation", len(fake.calls))
	}
}

func TestTaskActionResumeUsesRunningStringSpec(t *testing.T) {
	fake := &fakeDrive{t: t}
	fake.replyTo = func(call fakeDriveCall) (int, string, error) {
		if call.Method == http.MethodGet && queryOf(t, call.Path).Get("type") == "user#runner" {
			return 200, `{"tasks":[{"params":{"target":"device_id#current"}}]}`, nil
		}
		if call.Method == http.MethodGet && strings.Contains(queryOf(t, call.Path).Get("filters"), `"id"`) {
			return 200, `{"tasks":[{"id":"task-1","space":"device_id#current","type":"user#download-url","params":{"url":"magnet:?xt=urn:btih:test"}}]}`, nil
		}
		if call.Method == http.MethodPatch && call.Path == "/drive/v1/task" {
			return 200, `{"HttpStatus":0}`, nil
		}
		return 0, "", errors.New("unexpected drive call")
	}

	rec := serveAPI(t, &XLAPI{dc: fake}, http.MethodPost, "/tasks/task-1/action", `{"action":"resume"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	lookupQuery := queryOf(t, fake.calls[1].Path)
	if lookupQuery.Get("space") != "device_id#current" {
		t.Fatalf("task lookup space = %q", lookupQuery.Get("space"))
	}
	patchCall := fake.calls[2]
	if patchCall.Space != "" {
		t.Fatalf("patch transport device space = %q, want panel-compatible empty value", patchCall.Space)
	}
	body := patchCall.Body.(map[string]any)
	if body["space"] != "device_id#current" {
		t.Fatalf("patch body space = %#v", body["space"])
	}
	setParams := body["set_params"].(map[string]any)
	if setParams["spec"] != `{"phase":"running"}` {
		t.Fatalf("spec = %#v, want JSON string", setParams["spec"])
	}
}

func TestTaskFilesReparsesOriginalURL(t *testing.T) {
	const magnet = "magnet:?xt=urn:btih:task-url"
	fake := &fakeDrive{t: t}
	fake.replyTo = func(call fakeDriveCall) (int, string, error) {
		if call.Method == http.MethodGet && queryOf(t, call.Path).Get("type") == "user#runner" {
			return 200, `{"tasks":[{"params":{"target":"device_id#current"}}]}`, nil
		}
		if call.Method == http.MethodGet && strings.Contains(queryOf(t, call.Path).Get("filters"), `"id"`) {
			return 200, `{"tasks":[{"id":"task-1","space":"device_id#old","type":"user#download-url","params":{"url":"` + magnet + `"}}]}`, nil
		}
		if call.Method == http.MethodPost && call.Path == "/drive/v1/resource/list" {
			return 200, `{"list":{"resources":[{"name":"parsed"}]}}`, nil
		}
		return 0, "", errors.New("unexpected drive call")
	}

	rec := serveAPI(t, &XLAPI{dc: fake}, http.MethodGet, "/tasks/task-1/files", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	lookupQuery := queryOf(t, fake.calls[1].Path)
	if lookupQuery.Get("space") != "device_id#current" {
		t.Fatalf("task lookup space = %q", lookupQuery.Get("space"))
	}
	parseCall := fake.calls[2]
	parseBody := parseCall.Body.(map[string]any)
	if parseCall.Space != "" || parseBody["urls"] != magnet {
		t.Fatalf("files parse call = %#v", parseCall)
	}
	if _, exists := parseBody["id"]; exists {
		t.Fatalf("resource/list must parse URL, not an existing task id: %#v", parseBody)
	}
}
