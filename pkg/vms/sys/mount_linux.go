//go:build linux

package sys

import "syscall"

// Linux 平台真实实现

func mount(source, target, fstype string, flags uintptr, data string) error {
	return syscall.Mount(source, target, fstype, flags, data)
}

const (
	MS_BIND    = syscall.MS_BIND
	MNT_DETACH = syscall.MNT_DETACH
	MNT_FORCE  = syscall.MNT_FORCE
)
