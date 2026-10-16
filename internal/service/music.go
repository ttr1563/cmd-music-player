// Package service isolates YouTube Music's unofficial read-only API.
package service

import (
	"bytes"
	"context"
	"crypto/sha1"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	youtube "github.com/kkdai/youtube/v2"
	"github.com/ttr1563/cmd-music-player/internal/store"
)

var VideoID = regexp.MustCompile(`^[A-Za-z0-9_-]{11}$`)
var playlistID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,150}$`)
var clientVersion = regexp.MustCompile(`"INNERTUBE_CLIENT_VERSION"\s*:\s*"([0-9.]+)"`)
var errConnect = errors.New("YouTube Musicへ接続できません。接続とログイン状態を確認してください。")

type Item struct{ ID, Title, Subtitle, Kind string }
type Music struct {
	Headers store.Headers
	HTTP    *http.Client
	mu      sync.Mutex
	version string
}

func New(h store.Headers) *Music {
	return &Music{Headers: h, HTTP: &http.Client{Timeout: 15 * time.Second, CheckRedirect: func(r *http.Request, via []*http.Request) error {
		if len(via) > 5 || r.URL.Scheme != "https" || r.URL.Hostname() != "music.youtube.com" {
			return errConnect
		}
		return nil
	}}}
}
func LoginHeaders(cookie, authorization, user, page string) (store.Headers, error) {
	for _, s := range []string{cookie, authorization, user, page} {
		if strings.ContainsAny(s, "\r\n") {
			return nil, errors.New("ヘッダーの値を1行で入力してください。")
		}
	}
	index, err := strconv.Atoi(user)
	if err != nil || index < 0 || cookie == "" || !strings.Contains(authorization, "SAPISIDHASH") {
		return nil, errors.New("同じリクエストのCookie・Authorization・X-Goog-Authuserを入力してください。")
	}
	return store.Headers{"cookie": cookie, "authorization": authorization, "x-goog-authuser": user, "x-goog-pageid": page}, nil
}
func applyHeaders(req *http.Request, h store.Headers) {
	req.Header.Set("Origin", "https://music.youtube.com")
	req.Header.Set("Referer", "https://music.youtube.com/")
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
	for _, k := range []string{"cookie", "authorization", "x-goog-authuser", "x-goog-pageid"} {
		if h[k] != "" {
			req.Header.Set(k, h[k])
		}
	}
	// Refresh the short-lived hash in memory; never persist regenerated credentials.
	if h["cookie"] != "" {
		cookies := &http.Request{Header: http.Header{"Cookie": []string{h["cookie"]}}}
		sap := ""
		for _, c := range cookies.Cookies() {
			if c.Name == "SAPISID" {
				sap = c.Value
				break
			}
			if c.Name == "__Secure-3PAPISID" {
				sap = c.Value
			}
		}
		if sap != "" {
			stamp := strconv.FormatInt(time.Now().Unix(), 10)
			sum := sha1.Sum([]byte(stamp + " " + sap + " https://music.youtube.com"))
			req.Header.Set("Authorization", fmt.Sprintf("SAPISIDHASH %s_%x", stamp, sum))
		}
	}
}
func (m *Music) init(ctx context.Context) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.version != "" {
		return nil
	}
	req, _ := http.NewRequestWithContext(ctx, "GET", "https://music.youtube.com/", nil)
	applyHeaders(req, m.Headers)
	resp, err := m.HTTP.Do(req)
	if err != nil {
		return errConnect
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil || resp.StatusCode != 200 {
		return errConnect
	}
	match := clientVersion.FindSubmatch(b)
	if len(match) != 2 {
		return errConnect
	}
	m.version = string(match[1])
	return nil
}
func (m *Music) call(ctx context.Context, endpoint string, payload map[string]any) (any, error) {
	if err := m.init(ctx); err != nil {
		return nil, err
	}
	m.mu.Lock()
	version := m.version
	m.mu.Unlock()
	payload["context"] = map[string]any{"client": map[string]any{"clientName": "WEB_REMIX", "clientVersion": version, "hl": "ja", "gl": "JP"}, "user": map[string]any{}}
	body, _ := json.Marshal(payload)
	req, _ := http.NewRequestWithContext(ctx, "POST", "https://music.youtube.com/youtubei/v1/"+endpoint+"?prettyPrint=false", bytes.NewReader(body))
	applyHeaders(req, m.Headers)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Youtube-Client-Name", "67")
	req.Header.Set("X-Youtube-Client-Version", version)
	resp, err := m.HTTP.Do(req)
	if err != nil {
		return nil, errConnect
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, errConnect
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	var data any
	if err != nil || json.Unmarshal(b, &data) != nil || object(data)["error"] != nil {
		return nil, errConnect
	}
	return data, nil
}
func object(v any) map[string]any { m, _ := v.(map[string]any); return m }
func path(v any, keys ...string) any {
	for _, k := range keys {
		v = object(v)[k]
	}
	return v
}
func text(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	m := object(v)
	if s, ok := m["simpleText"].(string); ok {
		return s
	}
	var b strings.Builder
	if runs, ok := m["runs"].([]any); ok {
		for _, r := range runs {
			b.WriteString(text(path(r, "text")))
		}
	}
	return b.String()
}
func walk(v any, fn func(string, any)) {
	switch x := v.(type) {
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			fn(k, x[k])
			walk(x[k], fn)
		}
	case []any:
		for _, item := range x {
			walk(item, fn)
		}
	}
}
func items(data any, kind string, limit int) []Item {
	result := []Item{}
	seen := map[string]bool{}
	walk(data, func(key string, v any) {
		if len(result) >= limit {
			return
		}
		row := object(v)
		var item Item
		if kind == "song" && key == "musicResponsiveListItemRenderer" {
			if path(row, "isPlayable") == false {
				return
			}
			item.ID = text(path(row, "playlistItemData", "videoId"))
			if item.ID == "" {
				walk(row["overlay"], func(k string, v any) {
					if k == "videoId" && item.ID == "" {
						item.ID = text(v)
					}
				})
			}
			if !VideoID.MatchString(item.ID) {
				return
			}
			cols, _ := row["flexColumns"].([]any)
			if len(cols) > 0 {
				item.Title = text(path(cols[0], "musicResponsiveListItemFlexColumnRenderer", "text"))
			}
			if len(cols) > 1 {
				item.Subtitle = text(path(cols[1], "musicResponsiveListItemFlexColumnRenderer", "text"))
			}
		} else if kind == "playlist" && key == "musicTwoRowItemRenderer" {
			item.ID = text(path(row, "navigationEndpoint", "browseEndpoint", "browseId"))
			if !strings.HasPrefix(item.ID, "VL") {
				return
			}
			item.ID = strings.TrimPrefix(item.ID, "VL")
			item.Title = text(row["title"])
			item.Subtitle = text(row["subtitle"])
		} else {
			return
		}
		if item.Title == "" || seen[item.ID] {
			return
		}
		seen[item.ID] = true
		item.Kind = kind
		result = append(result, item)
	})
	return result
}
func (m *Music) Browse(ctx context.Context, operation, arg string) ([]Item, error) {
	endpoint := "browse"
	kind := "song"
	limit := 100
	body := map[string]any{}
	switch operation {
	case "search":
		endpoint = "search"
		limit = 30
		body["query"] = arg
		body["params"] = "EgWKAQIIAWoKEAkQBRAKEAMQBA%3D%3D"
	case "library", "playlists":
		if len(m.Headers) == 0 {
			return nil, errors.New("fest login 名前でログインしてください。")
		}
		body["browseId"] = "FEmusic_liked_videos"
		if operation == "playlists" {
			kind = "playlist"
			body["browseId"] = "FEmusic_liked_playlists"
		}
	case "playlist":
		if !playlistID.MatchString(arg) {
			return nil, errors.New("プレイリストIDが不正です。")
		}
		body["browseId"] = "VL" + strings.TrimPrefix(arg, "VL")
	default:
		return nil, errors.New("未対応の操作です。")
	}
	data, err := m.call(ctx, endpoint, body)
	if err != nil {
		return nil, err
	}
	result := items(data, kind, limit)
	seen := map[string]bool{}
	for _, i := range result {
		seen[i.ID] = true
	}
	for page := 0; page < 4 && len(result) < limit && operation != "search"; page++ {
		token := ""
		walk(data, func(k string, v any) {
			if k == "nextContinuationData" && token == "" {
				token = text(path(v, "continuation"))
			}
		})
		if token == "" {
			break
		}
		data, err = m.call(ctx, endpoint, map[string]any{"continuation": token})
		if err != nil {
			return nil, err
		}
		for _, i := range items(data, kind, limit-len(result)) {
			if !seen[i.ID] {
				result = append(result, i)
				seen[i.ID] = true
			}
		}
	}
	return result, nil
}
func (m *Music) Account(ctx context.Context) (string, error) {
	data, err := m.call(ctx, "account/account_menu", map[string]any{})
	if err != nil {
		return "", err
	}
	name := ""
	walk(data, func(k string, v any) {
		if k == "activeAccountHeaderRenderer" {
			name = text(path(v, "accountName"))
		}
	})
	if name == "" {
		return "", errors.New("選択したアカウントを確認できません。保存していません。")
	}
	return name, nil
}

type credentialTransport struct {
	base    http.RoundTripper
	headers store.Headers
	version string
}

func (t credentialTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	r = r.Clone(r.Context())
	host := r.URL.Hostname()
	if r.URL.Scheme != "https" || !(host == "www.youtube.com" || host == "music.youtube.com" || strings.HasSuffix(host, ".googlevideo.com")) {
		return nil, errConnect
	}
	if host == "www.youtube.com" || host == "music.youtube.com" {
		if len(t.headers) > 0 {
			query := r.URL.Query()
			query.Set("authuser", t.headers["x-goog-authuser"])
			r.URL.RawQuery = query.Encode()
			if r.Method == http.MethodPost && r.URL.Path == "/youtubei/v1/player" {
				raw, err := io.ReadAll(io.LimitReader(r.Body, 128001))
				r.Body.Close()
				if err != nil || len(raw) > 128000 {
					return nil, errConnect
				}
				var body map[string]any
				if json.Unmarshal(raw, &body) != nil {
					return nil, errConnect
				}
				contextBody := object(body["context"])
				if contextBody == nil {
					return nil, errConnect
				}
				contextBody["client"] = map[string]any{"clientName": "WEB_REMIX", "clientVersion": t.version, "hl": "ja", "gl": "JP"}
				user := map[string]any{}
				if page := t.headers["x-goog-pageid"]; page != "" {
					user["onBehalfOfUser"] = page
				}
				contextBody["user"] = user
				encoded, err := json.Marshal(body)
				if err != nil {
					return nil, errConnect
				}
				r.Body = io.NopCloser(bytes.NewReader(encoded))
				r.ContentLength = int64(len(encoded))
				r.GetBody = func() (io.ReadCloser, error) { return io.NopCloser(bytes.NewReader(encoded)), nil }
			}
		}
		if len(t.headers) > 0 {
			applyHeaders(r, t.headers)
		}
	} else {
		r.Header.Del("Cookie")
		r.Header.Del("Authorization")
		r.Header.Del("X-Goog-Authuser")
		r.Header.Del("X-Goog-Pageid")
	}
	return t.base.RoundTrip(r)
}
func (m *Music) Resolve(ctx context.Context, id string) (string, error) {
	if !VideoID.MatchString(id) {
		return "", errors.New("曲IDが不正です。")
	}
	ctx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()
	// A fresh client avoids sharing mutable extractor caches across cancelled requests.
	if len(m.Headers) > 0 {
		if err := m.init(ctx); err != nil {
			return "", err
		}
	}
	m.mu.Lock()
	version := m.version
	m.mu.Unlock()
	client := youtube.Client{HTTPClient: &http.Client{Timeout: 15 * time.Second, Transport: credentialTransport{base: http.DefaultTransport, headers: m.Headers, version: version}}}
	video, err := client.GetVideoContext(ctx, id)
	if err != nil {
		return "", errors.New("音声を取得できません。ログイン状態またはサービス側の変更を確認してください。")
	}
	formats := video.Formats.Type("audio")
	if len(formats) == 0 {
		return "", errors.New("再生可能な音声がありません。")
	}
	formats.Sort()
	for _, format := range formats {
		if format.AudioChannels == 0 || format.QualityLabel != "" {
			continue
		}
		if !(strings.Contains(format.MimeType, "mp4") || strings.Contains(format.MimeType, "webm")) {
			continue
		}
		value, err := client.GetStreamURLContext(ctx, video, &format)
		if err != nil {
			continue
		}
		if ValidateMediaURL(value) == nil {
			return value, nil
		}
	}
	return "", errors.New("AAC・Opusの音声URLを取得できません。")
}
func ValidateMediaURL(raw string) error {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.User != nil || u.Port() != "" || !strings.HasSuffix(u.Hostname(), ".googlevideo.com") {
		return errors.New("許可されていない音声URLです。")
	}
	return nil
}
