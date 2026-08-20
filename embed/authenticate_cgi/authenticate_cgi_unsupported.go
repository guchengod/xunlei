//go:build !linux

package authenticate_cgi

// 非 Linux 平台: 该 CGI 二进制只随 Linux 目标嵌入 (authenticate_cgi_linux_*.go),
// 这里提供一个空占位, 仅保证模块在非 Linux 主机上可编译; 运行期不会被使用。
var Bytes []byte
