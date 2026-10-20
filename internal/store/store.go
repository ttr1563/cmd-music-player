// Package store preserves the Python application's config and vault v1 formats.
package store

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"

	"golang.org/x/crypto/scrypt"
)

const marker = "music-cli-local:v1\n"
const aad = "music-cli-local/vault/v1"

var accountPattern = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}$`)

type Headers map[string]string
type Accounts map[string]Headers
type Config struct {
	Version int     `json:"version"`
	Service string  `json:"service"`
	Account *string `json:"account"`
	Volume  int     `json:"volume"`
}
type Store struct {
	Dir      string
	revision [32]byte
}

func DefaultConfig() Config { return Config{Version: 1, Service: "youtube-music", Volume: 70} }
func AccountName(name string) error {
	if !accountPattern.MatchString(name) {
		return errors.New("アカウント名は英数字で始まる40文字以内の英数字・_・-にしてください。")
	}
	return nil
}
func (c Config) Validate() error {
	if c.Version != 1 {
		return errors.New("未対応の設定形式です。上書きしません。")
	}
	if c.Service != "youtube-music" {
		return errors.New("対応サービスはyoutube-musicです。")
	}
	if c.Account != nil {
		if err := AccountName(*c.Account); err != nil {
			return err
		}
	}
	if c.Volume < 0 || c.Volume > 100 {
		return errors.New("音量は0〜100の整数にしてください。")
	}
	return nil
}
func New(dir string) (*Store, error) {
	if dir == "" {
		dir = os.Getenv("MUSIC_CLI_HOME")
	}
	if dir == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return nil, err
		}
		base := os.Getenv("XDG_CONFIG_HOME")
		switch runtime.GOOS {
		case "darwin":
			base = filepath.Join(home, "Library", "Application Support")
		case "windows":
			base = os.Getenv("LOCALAPPDATA")
			if base == "" {
				base = filepath.Join(home, "AppData", "Local")
			}
		default:
			if base == "" {
				base = filepath.Join(home, ".config")
			}
		}
		dir = filepath.Join(base, "music-cli")
	}
	if strings.HasPrefix(dir, "~/") || strings.HasPrefix(dir, "~\\") {
		home, err := os.UserHomeDir()
		if err != nil {
			return nil, err
		}
		dir = filepath.Join(home, dir[2:])
	}
	absolute, err := filepath.Abs(dir)
	if err != nil {
		return nil, err
	}
	s := &Store{Dir: absolute}
	return s, s.Check()
}
func (s *Store) path(name string) (string, error) {
	p := filepath.Join(s.Dir, name)
	st, err := os.Lstat(p)
	if err == nil && (st.Mode()&os.ModeSymlink != 0 || !st.Mode().IsRegular()) {
		return "", errors.New("データファイルが通常ファイルではありません。")
	}
	if err != nil && !os.IsNotExist(err) {
		return "", err
	}
	return p, nil
}
func (s *Store) Check() error {
	home, _ := os.UserHomeDir()
	real, err := filepath.EvalSymlinks(s.Dir)
	if err == nil && (real == home || filepath.Dir(real) == real) {
		return errors.New("ホーム・ルートはデータ領域にできません。")
	}
	st, err := os.Lstat(s.Dir)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return errors.New("専用データ領域を指定してください。")
	}
	if runtime.GOOS != "windows" && st.Mode().Perm()&0077 != 0 {
		return errors.New("データ領域をchmod 700で所有者限定にしてください。")
	}
	p, err := s.path(".music-cli")
	if err != nil {
		return err
	}
	b, err := os.ReadFile(p)
	if err != nil || string(b) != marker {
		return errors.New("専用データ領域ではありません。別の新しいパスを指定してください。")
	}
	return nil
}
func (s *Store) ensure() error {
	if err := s.Check(); err != nil {
		return err
	}
	_, err := os.Stat(s.Dir)
	if !os.IsNotExist(err) {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(s.Dir), 0700); err != nil {
		return err
	}
	if err = os.Mkdir(s.Dir, 0700); err != nil {
		return err
	}
	return s.write(".music-cli", []byte(marker))
}
func (s *Store) write(name string, data []byte) error {
	p, err := s.path(name)
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(s.Dir, ".write-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(data); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(f.Name(), p)
}
func (s *Store) lock(fn func() error) error {
	if err := s.ensure(); err != nil {
		return err
	}
	p := filepath.Join(s.Dir, ".write-lock")
	if err := os.Mkdir(p, 0700); err != nil {
		return errors.New("別の設定変更処理が実行中です。上書きしません。")
	}
	defer os.Remove(p)
	return fn()
}
func (s *Store) Config() (Config, error) {
	c := DefaultConfig()
	if err := s.Check(); err != nil {
		return c, err
	}
	p, err := s.path("config.json")
	if err != nil {
		return c, err
	}
	b, err := os.ReadFile(p)
	if os.IsNotExist(err) {
		return c, nil
	}
	if err != nil {
		return c, err
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(b, &fields) != nil {
		return c, errors.New("設定が不正です。")
	}
	for _, k := range []string{"version", "service", "account", "volume"} {
		if _, ok := fields[k]; !ok {
			return c, errors.New("設定項目が不足しています。")
		}
	}
	c = Config{}
	if bytes.Equal(fields["volume"], []byte("null")) || json.Unmarshal(b, &c) != nil {
		return c, errors.New("設定が不正です。")
	}
	return c, c.Validate()
}
func (s *Store) SaveConfig(c Config) error {
	if err := c.Validate(); err != nil {
		return err
	}
	b, _ := json.MarshalIndent(c, "", "  ")
	return s.lock(func() error { return s.write("config.json", b) })
}
func (s *Store) HasVault() bool {
	p, err := s.path("vault.enc")
	if err != nil {
		return false
	}
	_, err = os.Stat(p)
	return err == nil
}
func (s *Store) vaultBytes() ([]byte, error) {
	p, err := s.path("vault.enc")
	if err != nil {
		return nil, err
	}
	f, err := os.Open(p)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, 2_000_001))
	if len(b) > 2_000_000 {
		return nil, errors.New("認証ファイルが大きすぎます。")
	}
	return b, err
}
func digest(b []byte) [32]byte {
	if b == nil {
		return [32]byte{}
	}
	return sha256.Sum256(b)
}

type envelope struct {
	Version int    `json:"version"`
	Salt    string `json:"salt"`
	Nonce   string `json:"nonce"`
	Data    string `json:"data"`
}

func aead(phrase string, salt []byte) (cipher.AEAD, error) {
	if phrase == "" {
		return nil, errors.New("パスフレーズは必須です。")
	}
	key, err := scrypt.Key([]byte(phrase), salt, 32768, 8, 1, 32)
	if err != nil {
		return nil, err
	}
	defer clear(key)
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(block)
}
func (s *Store) Vault(phrase string) (Accounts, error) {
	if err := s.Check(); err != nil {
		return nil, err
	}
	b, err := s.vaultBytes()
	if err != nil {
		return nil, err
	}
	if b == nil {
		s.revision = [32]byte{}
		return Accounts{}, nil
	}
	var e envelope
	if json.Unmarshal(b, &e) != nil || e.Version != 1 {
		return nil, errors.New("未対応または不正な認証形式です。上書きしません。")
	}
	salt, e1 := base64.StdEncoding.Strict().DecodeString(e.Salt)
	nonce, e2 := base64.StdEncoding.Strict().DecodeString(e.Nonce)
	data, e3 := base64.StdEncoding.Strict().DecodeString(e.Data)
	if e1 != nil || e2 != nil || e3 != nil || len(salt) != 16 || len(nonce) != 12 {
		return nil, errors.New("認証ファイルが不正です。")
	}
	g, err := aead(phrase, salt)
	if err != nil {
		return nil, err
	}
	plain, err := g.Open(nil, nonce, data, []byte(aad))
	if err != nil {
		return nil, errors.New("パスフレーズが違うか、認証ファイルが破損しています。")
	}
	defer clear(plain)
	var accounts Accounts
	if json.Unmarshal(plain, &accounts) != nil || accounts == nil {
		return nil, errors.New("認証ファイルが不正です。")
	}
	for name, h := range accounts {
		if AccountName(name) != nil || h == nil {
			return nil, errors.New("保存アカウントが不正です。")
		}
	}
	s.revision = digest(b)
	return accounts, nil
}
func (s *Store) checkRevision() error {
	b, err := s.vaultBytes()
	if err != nil {
		return err
	}
	if digest(b) != s.revision {
		return errors.New("認証情報が別の処理で更新されました。上書きしません。")
	}
	return nil
}
func (s *Store) SaveVault(accounts Accounts, phrase string) error {
	for name, h := range accounts {
		if AccountName(name) != nil || h == nil {
			return errors.New("保存アカウントが不正です。")
		}
	}
	salt := make([]byte, 16)
	nonce := make([]byte, 12)
	if _, err := rand.Read(salt); err != nil {
		return err
	}
	if _, err := rand.Read(nonce); err != nil {
		return err
	}
	g, err := aead(phrase, salt)
	if err != nil {
		return err
	}
	plain, err := json.Marshal(accounts)
	if err != nil {
		return err
	}
	defer clear(plain)
	data := g.Seal(nil, nonce, plain, []byte(aad))
	b, _ := json.Marshal(envelope{1, base64.StdEncoding.EncodeToString(salt), base64.StdEncoding.EncodeToString(nonce), base64.StdEncoding.EncodeToString(data)})
	return s.lock(func() error {
		if err := s.checkRevision(); err != nil {
			return err
		}
		if err := s.write("vault.enc", b); err != nil {
			return err
		}
		s.revision = digest(b)
		return nil
	})
}
func (s *Store) RemoveVault() error {
	return s.lock(func() error {
		if err := s.checkRevision(); err != nil {
			return err
		}
		p, err := s.path("vault.enc")
		if err != nil {
			return err
		}
		if err = os.Remove(p); err != nil && !os.IsNotExist(err) {
			return err
		}
		s.revision = [32]byte{}
		return nil
	})
}
func (s *Store) Purge() error {
	if err := s.Check(); err != nil {
		return err
	}
	if _, err := os.Stat(s.Dir); os.IsNotExist(err) {
		return nil
	}
	err := s.lock(func() error {
		paths := []string{}
		for _, n := range []string{"config.json", "vault.enc"} {
			p, err := s.path(n)
			if err != nil {
				return err
			}
			paths = append(paths, p)
		}
		for _, p := range paths {
			if err := os.Remove(p); err != nil && !os.IsNotExist(err) {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return err
	}
	entries, err := os.ReadDir(s.Dir)
	if err != nil {
		return err
	}
	if len(entries) == 1 && entries[0].Name() == ".music-cli" {
		if err = os.Remove(filepath.Join(s.Dir, ".music-cli")); err != nil {
			return err
		}
		return os.Remove(s.Dir)
	}
	return nil
}
func SafeError(err error) string {
	var pathError *os.PathError
	if errors.As(err, &pathError) {
		return fmt.Sprintf("ファイル操作に失敗しました: %s", pathError.Op)
	}
	return err.Error()
}
