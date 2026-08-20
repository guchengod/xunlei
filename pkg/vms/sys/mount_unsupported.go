//go:build !linux

package sys

import (
	"fmt"
	"runtime"
)

// 非 Linux 平台: 仅保证编译通过, 运行期必然返回错误 (chroot/mount 仅 Linux 支持)。

func mount(source, target, fstype string, flags uintptr, data string) error {
	return fmt.Errorf("mount is not supported on %s", runtime.GOOS)
}

const (
	MS_BIND    = 0x1000
	MNT_DETACH = 0x0002
	MNT_FORCE  = 0x0001
)
