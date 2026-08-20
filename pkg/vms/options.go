package vms

import (
	"context"
	"path/filepath"

	"github.com/cnk3x/xunlei/pkg/utils"
	"github.com/cnk3x/xunlei/pkg/vms/sys"
)

func Root(root string) Option { return func(ro *options) { ro.root = root } }

func Run(run func(ctx context.Context) error) Option { return func(ro *options) { ro.run = run } }

func User[U, G utils.IntT | utils.UintT](uid U, gid G) Option {
	return func(ro *options) { ro.uid, ro.gid = int(uid), int(gid) }
}

func Wait(wait ...bool) Option {
	return func(ro *options) { ro.wait = len(wait) == 0 || wait[0] }
}

func After(after func(ctx context.Context, runErr error) (err error)) Option {
	return func(ro *options) { ro.after = after }
}

func Before(before func(ctx context.Context) (undo func(), err error)) Option {
	return func(ro *options) { ro.before = before }
}

func Basic(ro *options) {
	ro.mounts = append(ro.mounts,
		// proc/dev 挂载优先; 平台受限(如飞牛禁止 privileged)时失败会自动跳过降级, 不阻塞启动
		sys.MountOptions{Target: filepath.Join(ro.root, "proc"), Source: "proc", Fstype: "proc", Optional: true},
		sys.MountOptions{Target: filepath.Join(ro.root, "dev"), Source: "devtmpfs", Fstype: "devtmpfs", Data: "mode=0755", Optional: true}, //tmpfs
		sys.MountOptions{Target: filepath.Join(ro.root, "sys"), Source: "sysfs", Fstype: "sysfs", Optional: true},
		sys.MountOptions{Target: filepath.Join(ro.root, "tmp"), Source: "tmpfs", Fstype: "tmpfs", Data: "mode=0777,size=100m", Optional: true},
	)
}

func Links(files ...string) Option {
	return func(ro *options) {
		for _, file := range files {
			mOpts := sys.LinkOptions{
				Source:   file,
				Optional: true,
				DirMode:  0777,
			}
			ro.links = append(ro.links, mOpts)
		}
	}
}

func Binds(dirs ...string) Option {
	return func(ro *options) {
		for _, dir := range dirs {
			mOpts := sys.BindOptions{
				Source:   dir,
				Optional: true,
			}
			ro.binds = append(ro.binds, mOpts)
		}
	}
}

func Symlink(source, target string) Option {
	return func(ro *options) {
		ro.symbols = append(ro.symbols, sys.LinkOptions{
			Source:   source,
			Target:   target,
			Optional: true,
			DirMode:  0777,
		})
	}
}
