# tldr page for `rmdir`
# Source: https://github.com/tldr-pages/tldr (pages/common|linux/rmdir.md)

# rmdir

> Remove directories without files.
> See also: `rm`.
> More information: <https://www.gnu.org/software/coreutils/manual/html_node/rmdir-invocation.html>.

- Remove specific directories:

`rmdir {{path/to/directory1 path/to/directory2 ...}}`

- Remove specific nested directories recursively:

`rmdir {{[-p|--parents]}} {{path/to/directory1 path/to/directory2 ...}}`

- Clean a directory of empty directories:

`rmdir *`
