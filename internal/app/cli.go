package app

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/ttr1563/cmd-music-player/internal/player"
	"github.com/ttr1563/cmd-music-player/internal/service"
	"github.com/ttr1563/cmd-music-player/internal/store"
	"golang.org/x/term"
)

var Version = "0.4.0"

type console struct {
	in  *bufio.Reader
	out io.Writer
}

func (c console) line(prompt string) (string, error) {
	fmt.Fprint(c.out, prompt)
	s, err := c.in.ReadString('\n')
	return strings.TrimSpace(s), err
}
func (c console) secret(prompt string) (string, error) {
	if !term.IsTerminal(int(os.Stdin.Fd())) {
		return "", errors.New("認証情報は対話端末で非表示入力してください。")
	}
	fmt.Fprint(c.out, prompt)
	b, err := term.ReadPassword(int(os.Stdin.Fd()))
	fmt.Fprintln(c.out)
	if err != nil {
		return "", errors.New("非表示入力に失敗しました。")
	}
	defer clear(b)
	return string(b), nil
}
func (c console) confirm(prompt string) (bool, error) {
	s, err := c.line(prompt + " [y/N]: ")
	return strings.EqualFold(s, "y"), err
}
func (c console) unlock(s *store.Store) (store.Accounts, string, error) {
	phrase, err := c.secret("認証ファイルのパスフレーズ: ")
	if err != nil {
		return nil, "", err
	}
	accounts, err := s.Vault(phrase)
	return accounts, phrase, err
}
func (c console) login(ctx context.Context, s *store.Store, name string) error {
	if store.AccountName(name) != nil || name == "guest" {
		return errors.New("guest以外の有効なアカウント名を指定してください。")
	}
	accounts := store.Accounts{}
	phrase := ""
	var err error
	if s.HasVault() {
		accounts, phrase, err = c.unlock(s)
		if err != nil {
			return err
		}
	}
	fmt.Fprintln(c.out, "music.youtube.comで使うアカウントを選び、Networkのbrowseリクエストから値を入力してください。Googleパスワードは入力しません。")
	cookie, err := c.secret("Cookie: ")
	if err != nil {
		return err
	}
	authorization, err := c.secret("Authorization（SAPISIDHASH…）: ")
	if err != nil {
		return err
	}
	user, err := c.line("X-Goog-Authuser [0]: ")
	if err != nil {
		return err
	}
	if user == "" {
		user = "0"
	}
	page, err := c.line("X-Goog-Pageid（なければEnter）: ")
	if err != nil {
		return err
	}
	headers, err := service.LoginHeaders(cookie, authorization, user, page)
	if err != nil {
		return err
	}
	identity, err := service.New(headers).Account(ctx)
	if err != nil {
		return err
	}
	fmt.Fprintln(c.out, "確認したアカウント:", identity)
	yes, err := c.confirm("このアカウントを" + name + "として保存しますか？")
	if err != nil || !yes {
		return err
	}
	if _, ok := accounts[name]; ok {
		yes, err = c.confirm("同名の保存アカウントを置き換えますか？")
		if err != nil || !yes {
			return err
		}
	}
	if phrase == "" {
		phrase, err = c.secret("新しい保存用パスフレーズ（12文字以上）: ")
		if err != nil {
			return err
		}
		if utf8.RuneCountInString(phrase) < 12 {
			return errors.New("パスフレーズは12文字以上にしてください。")
		}
		again, err := c.secret("再入力: ")
		if err != nil {
			return err
		}
		if phrase != again {
			return errors.New("パスフレーズが一致しません。保存していません。")
		}
	}
	accounts[name] = headers
	if err = s.SaveVault(accounts, phrase); err != nil {
		return err
	}
	config, err := s.Config()
	if err != nil {
		return err
	}
	config.Account = &name
	if err = s.SaveConfig(config); err != nil {
		return err
	}
	fmt.Fprintln(c.out, "保存しました。festで起動できます。")
	return nil
}
func (c console) account(s *store.Store, name string) error {
	config, err := s.Config()
	if err != nil {
		return err
	}
	if name == "guest" {
		config.Account = nil
	} else {
		if !s.HasVault() {
			return errors.New("保存アカウントがありません。fest login 名前で登録してください。")
		}
		accounts, _, err := c.unlock(s)
		if err != nil {
			return err
		}
		if name == "" {
			names := []string{"guest"}
			for n := range accounts {
				names = append(names, n)
			}
			sort.Strings(names[1:])
			for i, n := range names {
				fmt.Fprintf(c.out, "%d. %s\n", i+1, n)
			}
			value, err := c.line("番号: ")
			if err != nil {
				return err
			}
			index, err := strconv.Atoi(value)
			if err != nil || index < 1 || index > len(names) {
				return errors.New("一覧の番号を選んでください。")
			}
			name = names[index-1]
		}
		if name == "guest" {
			config.Account = nil
		} else {
			if _, ok := accounts[name]; !ok {
				return errors.New("保存されていないアカウントです。")
			}
			config.Account = &name
		}
	}
	if err = s.SaveConfig(config); err != nil {
		return err
	}
	fmt.Fprintln(c.out, "使用アカウント:", name)
	return nil
}
func Help(out io.Writer) {
	fmt.Fprintln(out, "fest — YouTube Music terminal player\n\n使い方: fest [--guest] [--data-dir PATH] [command]\n\n  login NAME       アカウントを暗号化保存します\n  account [NAME]   使用アカウントを選びます（guestも指定可）\n  logout NAME      保存アカウントを削除します\n  service          サービスを選びます\n  config show|path|set KEY VALUE\n  doctor [--audio] 配布内容と音声出力を確認します\n  purge [--yes]    アプリの保存データを削除します\n  version          バージョンを表示します")
}
func Run(args []string) error {
	if len(args) == 1 && args[0] == "--internal-resolver" {
		os.Exit(service.ResolverMain())
	}
	flags := flag.NewFlagSet("fest", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	directory := flags.String("data-dir", "", "専用データ保存先")
	guest := flags.Bool("guest", false, "guestで起動")
	help := flags.Bool("help", false, "使い方")
	flags.BoolVar(help, "h", false, "使い方")
	if flags.Parse(args) != nil {
		return errors.New("引数が不正です。fest --helpを確認してください。")
	}
	if *help {
		Help(os.Stdout)
		return nil
	}
	args = flags.Args()
	if len(args) == 1 && args[0] == "version" {
		fmt.Fprintln(os.Stdout, "fest", Version, "Go", runtime.Version())
		return nil
	}
	s, err := store.New(*directory)
	if err != nil {
		return err
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
	defer cancel()
	c := console{bufio.NewReader(os.Stdin), os.Stdout}
	if len(args) == 0 {
		if !term.IsTerminal(int(os.Stdin.Fd())) || !term.IsTerminal(int(os.Stdout.Fd())) {
			return errors.New("festは対話端末で起動してください。")
		}
		config, err := s.Config()
		if err != nil {
			return err
		}
		if !*guest {
			if _, err := os.Stat(filepath.Join(s.Dir, "config.json")); os.IsNotExist(err) {
				fmt.Fprintln(c.out, "サービス: 1. YouTube Music")
				choice, err := c.line("番号 [1]: ")
				if err != nil {
					return err
				}
				if choice != "" && choice != "1" {
					return errors.New("1を選択してください。")
				}
				choice, err = c.line("1. guestで開始 / 2. login [1]: ")
				if err != nil {
					return err
				}
				if choice == "2" {
					name, err := c.line("保存アカウント名 [personal]: ")
					if err != nil {
						return err
					}
					if name == "" {
						name = "personal"
					}
					if err = c.login(ctx, s, name); err != nil {
						return err
					}
					config, err = s.Config()
					if err != nil {
						return err
					}
				} else if choice != "" && choice != "1" {
					return errors.New("1か2を選んでください。")
				}
				if err = s.SaveConfig(config); err != nil {
					return err
				}
			}
		}
		var headers store.Headers
		identity := "guest"
		if !*guest && config.Account != nil {
			accounts, _, err := c.unlock(s)
			if err != nil {
				return err
			}
			var ok bool
			headers, ok = accounts[*config.Account]
			if !ok {
				return errors.New("選択アカウントがありません。fest account guestで解除してください。")
			}
			identity = *config.Account
		}
		return TUI(ctx, service.New(headers), config, identity)
	}
	switch args[0] {
	case "login":
		if len(args) != 2 {
			return errors.New("fest login 名前を指定してください。")
		}
		return c.login(ctx, s, args[1])
	case "account":
		if len(args) > 2 {
			return errors.New("fest account [名前]を指定してください。")
		}
		name := ""
		if len(args) == 2 {
			name = args[1]
		}
		return c.account(s, name)
	case "logout":
		if len(args) != 2 {
			return errors.New("fest logout 名前を指定してください。")
		}
		accounts, phrase, err := c.unlock(s)
		if err != nil {
			return err
		}
		if _, ok := accounts[args[1]]; !ok {
			return errors.New("保存アカウントがありません。")
		}
		yes, err := c.confirm("指定した保存アカウントを削除しますか？")
		if err != nil || !yes {
			return err
		}
		delete(accounts, args[1])
		if len(accounts) == 0 {
			err = s.RemoveVault()
		} else {
			err = s.SaveVault(accounts, phrase)
		}
		if err != nil {
			return err
		}
		config, err := s.Config()
		if err != nil {
			return err
		}
		if config.Account != nil && *config.Account == args[1] {
			config.Account = nil
			err = s.SaveConfig(config)
		}
		return err
	case "service":
		if len(args) != 1 {
			return errors.New("fest serviceを指定してください。")
		}
		fmt.Fprintln(c.out, "1. YouTube Music")
		value, err := c.line("番号 [1]: ")
		if err != nil {
			return err
		}
		if value != "" && value != "1" {
			return errors.New("1を選んでください。")
		}
		config, err := s.Config()
		if err != nil {
			return err
		}
		return s.SaveConfig(config)
	case "config":
		return c.config(s, args[1:])
	case "purge":
		if len(args) > 2 || (len(args) == 2 && args[1] != "--yes") {
			return errors.New("fest purge [--yes]を指定してください。")
		}
		yes := len(args) == 2
		if !yes {
			fmt.Fprintln(c.out, "他のfestを終了してください。削除先:", s.Dir)
			yes, err = c.confirm("設定と保存アカウントを削除しますか？")
			if err != nil {
				return err
			}
		}
		if yes {
			return s.Purge()
		}
		return nil
	case "doctor":
		if len(args) > 2 || (len(args) == 2 && args[1] != "--audio") {
			return errors.New("fest doctor [--audio]を指定してください。")
		}
		fmt.Fprintln(c.out, "fest", Version, "/", runtime.GOOS, runtime.GOARCH, "/", runtime.Version())
		fmt.Fprintln(c.out, "サービス: YouTube Music / 認証保存: 暗号化ファイル / Keychain: 使用しません")
		fmt.Fprintln(c.out, "保存先:", s.Dir)
		decoder, err := player.Decoder()
		if err != nil {
			return err
		}
		fmt.Fprintln(c.out, "decoder:", decoder)
		if len(args) == 2 {
			if err = player.CheckAudio(); err != nil {
				return err
			}
			fmt.Fprintln(c.out, "OS音声出力を開けました（無音確認です）。")
		}
		fmt.Fprintln(c.out, "ログイン・実際の音楽再生はこの診断では確認しません。")
		return nil
	default:
		return errors.New("未対応のコマンドです。fest --helpを確認してください。")
	}
}
func (c console) config(s *store.Store, args []string) error {
	if len(args) == 1 {
		switch args[0] {
		case "path":
			fmt.Fprintln(c.out, filepath.Join(s.Dir, "config.json"))
			return nil
		case "show":
			config, err := s.Config()
			if err != nil {
				return err
			}
			b, _ := json.MarshalIndent(config, "", "  ")
			fmt.Fprintln(c.out, string(b))
			return nil
		}
	}
	if len(args) != 3 || args[0] != "set" {
		return errors.New("fest config show|path|set KEY VALUEを指定してください。")
	}
	if args[1] == "account" {
		return c.account(s, args[2])
	}
	config, err := s.Config()
	if err != nil {
		return err
	}
	switch args[1] {
	case "service":
		config.Service = args[2]
	case "volume":
		value, err := strconv.Atoi(args[2])
		if err != nil {
			return errors.New("音量は0〜100の整数にしてください。")
		}
		config.Volume = value
	default:
		return errors.New("設定キーはservice・account・volumeです。")
	}
	return s.SaveConfig(config)
}
