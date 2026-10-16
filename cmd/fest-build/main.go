// fest-build creates a native portable bundle, including its LGPL decoder sources.
package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

const version = "0.4.0-dev"
const sourceURL = "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz"
const sourceSHA = "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"

func run(ctx context.Context, dir string, env []string, name string, args ...string) error {
	c := exec.CommandContext(ctx, name, args...)
	c.Dir = dir
	c.Env = env
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	return c.Run()
}
func copyFile(from, to string) error {
	in, err := os.Open(from)
	if err != nil {
		return err
	}
	defer in.Close()
	info, err := in.Stat()
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(to), 0755); err != nil {
		return err
	}
	out, err := os.OpenFile(to, os.O_CREATE|os.O_EXCL|os.O_WRONLY, info.Mode().Perm())
	if err != nil {
		return err
	}
	_, err = io.Copy(out, in)
	closeErr := out.Close()
	if err != nil {
		return err
	}
	return closeErr
}
func checksum(p string) error {
	f, err := os.Open(p)
	if err != nil {
		return err
	}
	h := sha256.New()
	_, err = io.Copy(h, f)
	f.Close()
	if err != nil {
		return err
	}
	return os.WriteFile(p+".sha256", []byte(fmt.Sprintf("%x  %s\n", h.Sum(nil), filepath.Base(p))), 0644)
}
func archive(root, output string) error {
	f, err := os.Create(output)
	if err != nil {
		return err
	}
	defer f.Close()
	if strings.HasSuffix(output, ".zip") {
		z := zip.NewWriter(f)
		err = filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
			if err != nil {
				return err
			}
			if !info.Mode().IsRegular() {
				return nil
			}
			name, _ := filepath.Rel(filepath.Dir(root), p)
			header, err := zip.FileInfoHeader(info)
			if err != nil {
				return err
			}
			header.Name = filepath.ToSlash(name)
			header.Method = zip.Deflate
			w, err := z.CreateHeader(header)
			if err != nil {
				return err
			}
			r, err := os.Open(p)
			if err != nil {
				return err
			}
			defer r.Close()
			_, err = io.Copy(w, r)
			return err
		})
		closeErr := z.Close()
		if err != nil {
			return err
		}
		return closeErr
	}
	g := gzip.NewWriter(f)
	t := tar.NewWriter(g)
	err = filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		header, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return err
		}
		name, _ := filepath.Rel(filepath.Dir(root), p)
		header.Name = filepath.ToSlash(name)
		if err = t.WriteHeader(header); err != nil {
			return err
		}
		r, err := os.Open(p)
		if err != nil {
			return err
		}
		defer r.Close()
		_, err = io.Copy(t, r)
		return err
	})
	tc := t.Close()
	gc := g.Close()
	if err != nil {
		return err
	}
	if tc != nil {
		return tc
	}
	return gc
}
func build() error {
	ctx, cancel := context.WithTimeout(context.Background(), 18*time.Minute)
	defer cancel()
	root, err := os.Getwd()
	if err != nil {
		return err
	}
	if _, err = os.Stat(filepath.Join(root, "go.mod")); err != nil {
		return errors.New("repository rootで実行してください。")
	}
	target := runtime.GOOS + "-" + runtime.GOARCH
	switch target {
	case "linux-amd64", "darwin-arm64", "darwin-amd64", "windows-amd64":
	default:
		return errors.New("unsupported native target")
	}
	label := strings.ReplaceAll(target, "amd64", "x86_64")
	if runtime.GOOS == "windows" {
		label = "win32-x86_64"
	}
	name := "fest-" + version + "-" + label
	dist := filepath.Join(root, "dist")
	destination := filepath.Join(dist, name)
	if _, err = os.Stat(destination); !os.IsNotExist(err) {
		return errors.New("既存出力は上書きしません。")
	}
	temporary, err := os.MkdirTemp("", "fest-go-build-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(temporary)
	app := filepath.Join(temporary, "fest")
	audio := filepath.Join(app, "runtime")
	notices := filepath.Join(app, "notices")
	sources := filepath.Join(temporary, "audio-sources")
	for _, p := range []string{audio, notices, sources} {
		if err = os.MkdirAll(p, 0755); err != nil {
			return err
		}
	}
	archiveTool := "tar"
	if runtime.GOOS == "windows" {
		archiveTool = filepath.Join(os.Getenv("SystemRoot"), "System32", "tar.exe")
	}
	client := &http.Client{Timeout: 90 * time.Second}
	response, err := client.Get(sourceURL)
	if err != nil {
		return err
	}
	if response.StatusCode != 200 {
		response.Body.Close()
		return errors.New("FFmpeg download failed")
	}
	sourceArchive := filepath.Join(sources, "ffmpeg-9.0.2.tar.xz")
	f, err := os.Create(sourceArchive)
	if err != nil {
		response.Body.Close()
		return err
	}
	h := sha256.New()
	_, err = io.Copy(io.MultiWriter(f, h), io.LimitReader(response.Body, 32<<20))
	f.Close()
	response.Body.Close()
	if err != nil {
		return err
	}
	if hex.EncodeToString(h.Sum(nil)) != sourceSHA {
		return errors.New("FFmpeg source checksum mismatch")
	}
	if err = run(ctx, temporary, os.Environ(), archiveTool, "-xf", sourceArchive); err != nil {
		return err
	}
	tree := filepath.Join(temporary, "ffmpeg-9.0.2")
	prefix := filepath.Join(temporary, "prefix")
	env := append(os.Environ(), "CGO_ENABLED=0", "GOMAXPROCS=2")
	shell := "/bin/sh"
	makeTool := "make"
	flags := []string{"--prefix=" + filepath.ToSlash(prefix), "--disable-gpl", "--disable-version3", "--disable-nonfree", "--disable-autodetect", "--disable-network", "--disable-everything", "--disable-doc", "--disable-debug", "--disable-static", "--enable-shared", "--enable-ffmpeg", "--disable-ffprobe", "--disable-x86asm", "--disable-inline-asm", "--enable-decoder=aac,opus,pcm_s16le", "--enable-encoder=pcm_f32le,aac,opus", "--enable-demuxer=mov,matroska,wav", "--enable-muxer=pcm_f32le,mp4,webm", "--enable-protocol=pipe", "--enable-filter=abuffer,abuffersink,aresample,aformat,anull,atrim"}
	if runtime.GOOS == "darwin" {
		flags = append(flags, "--install-name-dir=@rpath", "--extra-ldflags=-Wl,-headerpad_max_install_names")
		env = append(env, "MACOSX_DEPLOYMENT_TARGET=14.0")
	}
	if runtime.GOOS == "windows" {
		vc := os.Getenv("VCToolsInstallDir")
		if vc == "" {
			return errors.New("Visual Studio Developer PowerShellで実行してください。")
		}
		env = append(env, "PATH="+filepath.Join(vc, "bin", "Hostx64", "x64")+";C:/msys64/usr/bin;"+os.Getenv("PATH"))
		shell = "C:/msys64/usr/bin/bash.exe"
		makeTool = "C:/msys64/usr/bin/make.exe"
		flags = append(flags, "--toolchain=msvc", "--arch=x86_64")
	}
	if err = run(ctx, tree, env, shell, append([]string{filepath.ToSlash(filepath.Join(tree, "configure"))}, flags...)...); err != nil {
		return err
	}
	config, err := os.ReadFile(filepath.Join(tree, "config.h"))
	if err != nil {
		return err
	}
	for _, option := range []string{"GPL", "NONFREE", "VERSION3"} {
		if !strings.Contains(string(config), "#define CONFIG_"+option+" 0") {
			return errors.New("FFmpeg license configuration failed")
		}
	}
	components, err := os.ReadFile(filepath.Join(tree, "config_components.h"))
	if err != nil {
		return err
	}
	if err = verifyComponents(components); err != nil {
		return err
	}
	if err = run(ctx, tree, env, makeTool, "-j2"); err != nil {
		return err
	}
	if err = run(ctx, tree, env, makeTool, "install"); err != nil {
		return err
	}

	exe := "fest"
	ffmpeg := "ffmpeg"
	if runtime.GOOS == "windows" {
		exe += ".exe"
		ffmpeg += ".exe"
	}
	if err = copyFile(filepath.Join(prefix, "bin", ffmpeg), filepath.Join(audio, ffmpeg)); err != nil {
		return err
	}
	libs := filepath.Join(prefix, "lib")
	if runtime.GOOS == "windows" {
		libs = filepath.Join(prefix, "bin")
	}
	entries, err := os.ReadDir(libs)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		n := entry.Name()
		if !strings.Contains(n, ".so") && !strings.HasSuffix(n, ".dylib") && !strings.HasSuffix(n, ".dll") {
			continue
		}
		to := filepath.Join(audio, "lib", n)
		if runtime.GOOS == "windows" {
			to = filepath.Join(audio, n)
		}
		if err = copyFile(filepath.Join(libs, n), to); err != nil {
			return err
		}
	}
	if runtime.GOOS == "linux" {
		if err = run(ctx, root, env, "patchelf", "--set-rpath", "$ORIGIN/lib", filepath.Join(audio, ffmpeg)); err != nil {
			return err
		}
		entries, _ := os.ReadDir(filepath.Join(audio, "lib"))
		for _, entry := range entries {
			if err = run(ctx, root, env, "patchelf", "--set-rpath", "$ORIGIN", filepath.Join(audio, "lib", entry.Name())); err != nil {
				return err
			}
		}
	}
	if runtime.GOOS == "darwin" {
		if err = run(ctx, root, env, "install_name_tool", "-add_rpath", "@executable_path/lib", filepath.Join(audio, ffmpeg)); err != nil {
			return err
		}
	}
	command := exec.CommandContext(ctx, filepath.Join(audio, ffmpeg), "-L")
	license, err := command.CombinedOutput()
	if err != nil {
		return fmt.Errorf("decoder license check could not start: %w: %s", err, license)
	}
	if err = verifyLicense(license); err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(notices, "FFMPEG-BUILD.txt"), append([]byte(strings.Join(flags, "\n")+"\n"), license...), 0644); err != nil {
		return err
	}
	if err = copyFile(filepath.Join(tree, "COPYING.LGPLv2.1"), filepath.Join(notices, "FFMPEG-LICENSE.txt")); err != nil {
		return err
	}
	for _, name := range []string{"LICENSE", "packaging/THIRD-PARTY.md"} {
		if err = copyFile(filepath.Join(root, name), filepath.Join(notices, filepath.Base(name))); err != nil {
			return err
		}
	}
	if err = run(ctx, root, env, "go", "build", "-trimpath", "-ldflags", "-s -w -X github.com/ttr1563/cmd-music-player/internal/app.Version="+version, "-o", filepath.Join(app, exe), "./cmd/fest"); err != nil {
		return err
	}
	for _, args := range [][]string{{"--help"}, {"version"}, {"--data-dir", filepath.Join(temporary, "smoke-data"), "doctor"}} {
		if err = run(ctx, root, env, filepath.Join(app, exe), args...); err != nil {
			return err
		}
	}
	if err = verifyDecoder(ctx, filepath.Join(audio, ffmpeg)); err != nil {
		return err
	}
	if err = goNotices(ctx, root, env, notices); err != nil {
		return err
	}
	hashes := map[string]string{}
	if err = filepath.Walk(app, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		f, err := os.Open(p)
		if err != nil {
			return err
		}
		h := sha256.New()
		_, err = io.Copy(h, f)
		f.Close()
		if err != nil {
			return err
		}
		relative, _ := filepath.Rel(app, p)
		hashes[filepath.ToSlash(relative)] = hex.EncodeToString(h.Sum(nil))
		return nil
	}); err != nil {
		return err
	}
	info, _ := json.MarshalIndent(map[string]any{"files": hashes, "target": target, "ffmpeg_source": sourceURL, "ffmpeg_sha256": sourceSHA, "configure": flags, "source_changes": "none", "go": runtime.Version()}, "", "  ")
	if err = os.WriteFile(filepath.Join(sources, "build.json"), info, 0644); err != nil {
		return err
	}
	if err = copyFile(filepath.Join(root, "cmd/fest-build/main.go"), filepath.Join(sources, "build.go")); err != nil {
		return err
	}
	if err = copyFile(filepath.Join(notices, "FFMPEG-LICENSE.txt"), filepath.Join(sources, "COPYING.LGPLv2.1")); err != nil {
		return err
	}
	if err = os.MkdirAll(destination, 0755); err != nil {
		return err
	}
	suffix := ".tar.gz"
	if runtime.GOOS == "windows" {
		suffix = ".zip"
	}
	output := filepath.Join(destination, name+suffix)
	if err = archive(app, output); err != nil {
		return err
	}
	if err = checksum(output); err != nil {
		return err
	}
	// Hide the build prefix to detect accidental links to files outside the bundle.
	if err = os.Rename(prefix, prefix+"-unused"); err != nil {
		return err
	}
	unpacked := filepath.Join(temporary, "unpacked")
	if err = os.Mkdir(unpacked, 0755); err != nil {
		return err
	}
	if err = run(ctx, root, env, archiveTool, "-xf", output, "-C", unpacked); err != nil {
		return err
	}
	if err = run(ctx, root, env, filepath.Join(unpacked, "fest", exe), "--data-dir", filepath.Join(temporary, "unpacked-data"), "doctor"); err != nil {
		return err
	}
	if err = verifyDecoder(ctx, filepath.Join(unpacked, "fest", "runtime", ffmpeg)); err != nil {
		return err
	}
	sourceOutput := filepath.Join(destination, name+".audio-sources.tar.gz")
	if err = archive(sources, sourceOutput); err != nil {
		return err
	}
	if err = checksum(sourceOutput); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(destination, name+".native.json"), info, 0644)
}
func main() {
	if err := build(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func goNotices(ctx context.Context, root string, env []string, notices string) error {
	command := exec.CommandContext(ctx, "go", "list", "-deps", "-json", "./cmd/fest")
	command.Dir = root
	command.Env = env
	data, err := command.Output()
	if err != nil {
		return err
	}
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	seen := map[string]bool{}
	for {
		var pkg struct {
			Module *struct {
				Path, Dir, Version string
				Main               bool
			}
		}
		err := decoder.Decode(&pkg)
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		m := pkg.Module
		if m == nil || m.Main || seen[m.Path] {
			continue
		}
		seen[m.Path] = true
		entries, err := os.ReadDir(m.Dir)
		if err != nil {
			return err
		}
		count := 0
		for _, entry := range entries {
			n := strings.ToUpper(entry.Name())
			if entry.IsDir() || !(strings.HasPrefix(n, "LICENSE") || strings.HasPrefix(n, "COPYING") || strings.HasPrefix(n, "NOTICE")) {
				continue
			}
			if err = copyFile(filepath.Join(m.Dir, entry.Name()), filepath.Join(notices, "go", filepath.FromSlash(m.Path), entry.Name())); err != nil {
				return err
			}
			count++
		}
		if count == 0 {
			return fmt.Errorf("missing license: %s", m.Path)
		}
	}
	return copyFile(filepath.Join(runtime.GOROOT(), "LICENSE"), filepath.Join(notices, "GO-LICENSE.txt"))
}

func verifyDecoder(ctx context.Context, decoder string) error {
	var wav bytes.Buffer
	wav.WriteString("RIFF")
	binary.Write(&wav, binary.LittleEndian, uint32(36+4800*4))
	wav.WriteString("WAVEfmt ")
	for _, v := range []any{uint32(16), uint16(1), uint16(2), uint32(48000), uint32(192000), uint16(4), uint16(16)} {
		binary.Write(&wav, binary.LittleEndian, v)
	}
	wav.WriteString("data")
	binary.Write(&wav, binary.LittleEndian, uint32(4800*4))
	for i := 0; i < 4800; i++ {
		sample := int16(8000 * math.Sin(2*math.Pi*440*float64(i)/48000))
		binary.Write(&wav, binary.LittleEndian, sample)
		binary.Write(&wav, binary.LittleEndian, sample)
	}
	for _, format := range []struct{ codec, container string }{{"aac", "mp4"}, {"opus", "webm"}} {
		args := []string{"-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-c:a", format.codec, "-strict", "-2", "-f", format.container}
		if format.container == "mp4" {
			args = append(args, "-movflags", "frag_keyframe+empty_moov")
		}
		args = append(args, "pipe:1")
		encode := exec.CommandContext(ctx, decoder, args...)
		encode.Stdin = bytes.NewReader(wav.Bytes())
		encoded, err := encode.Output()
		if err != nil {
			return fmt.Errorf("%s fixture encoding failed: %w", format.codec, err)
		}
		decode := exec.CommandContext(ctx, decoder, "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "pipe", "-i", "pipe:0", "-ac", "2", "-ar", "48000", "-f", "f32le", "pipe:1")
		decode.Stdin = bytes.NewReader(encoded)
		pcm, err := decode.Output()
		if err != nil || len(pcm) < 4800*8 {
			return fmt.Errorf("%s decoding failed: bytes=%d, error=%v", format.codec, len(pcm), err)
		}
		nonzero := false
		for _, b := range pcm {
			if b != 0 {
				nonzero = true
				break
			}
		}
		if !nonzero {
			return errors.New("decoded PCM is silent")
		}
	}
	return nil
}

func verifyLicense(output []byte) error {
	text := strings.Join(strings.Fields(string(output)), " ")
	if !strings.Contains(text, "GNU Lesser General Public License") || !strings.Contains(text, "version 2.1") {
		return errors.New("decoder license check failed")
	}
	return nil
}

func verifyComponents(config []byte) error {
	for _, name := range []string{"AAC_DECODER", "OPUS_DECODER", "PCM_F32LE_ENCODER", "PCM_F32LE_MUXER"} {
		if !strings.Contains(string(config), "#define CONFIG_"+name+" 1") {
			return fmt.Errorf("required audio component disabled: %s", name)
		}
	}
	return nil
}
