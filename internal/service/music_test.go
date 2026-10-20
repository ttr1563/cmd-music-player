package service

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/ttr1563/cmd-music-player/internal/store"
)

type transportFunc func(*http.Request) (*http.Response, error)

func (f transportFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestHeadersRejectNewlinesAndRequireAccount(t *testing.T) {
	for _, values := range [][4]string{{"a\r\nb", "SAPISIDHASH test", "0", ""}, {"a", "SAPISIDHASH test", "-1", ""}, {"a", "bad", "0", ""}} {
		if _, err := LoginHeaders(values[0], values[1], values[2], values[3]); err == nil {
			t.Fatal("invalid header accepted")
		}
	}
	h, err := LoginHeaders("a=b", "SAPISIDHASH fixture", "2", "brand")
	if err != nil || h["x-goog-authuser"] != "2" || h["x-goog-pageid"] != "brand" {
		t.Fatal("account selection lost")
	}
}
func TestMediaURLRestrictions(t *testing.T) {
	for _, u := range []string{"http://a.googlevideo.com/", "https://googlevideo.com/", "https://a.googlevideo.com.evil.test/", "https://user@a.googlevideo.com/", "https://a.googlevideo.com:444/", "file:///tmp/audio"} {
		if ValidateMediaURL(u) == nil {
			t.Fatal("unsafe URL accepted", u)
		}
	}
	if ValidateMediaURL("https://r1.googlevideo.com/videoplayback?fixture=true") != nil {
		t.Fatal("CDN rejected")
	}
}
func TestCredentialsNeverReachCDN(t *testing.T) {
	headers := store.Headers{"cookie": "private", "authorization": "SAPISIDHASH fixture", "x-goog-authuser": "2"}
	transport := credentialTransport{base: transportFunc(func(r *http.Request) (*http.Response, error) {
		for _, key := range []string{"Cookie", "Authorization", "X-Goog-Authuser"} {
			if r.Header.Get(key) != "" {
				t.Fatal("credential reached CDN", key)
			}
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(""))}, nil
	}), headers: headers}
	req, _ := http.NewRequest("GET", "https://r1.googlevideo.com/audio", nil)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	if _, err := transport.RoundTrip(req); err != nil {
		t.Fatal(err)
	}
}
func TestSearchParsesOnlySongRows(t *testing.T) {
	body := `{"contents":[{"musicResponsiveListItemRenderer":{"playlistItemData":{"videoId":"abcdefghijk"},"flexColumns":[{"musicResponsiveListItemFlexColumnRenderer":{"text":{"runs":[{"text":"Song"}]}}},{"musicResponsiveListItemFlexColumnRenderer":{"text":{"runs":[{"text":"Artist"}]}}}]}},{"musicResponsiveListItemRenderer":{"playlistItemData":{"videoId":"not-a-song"}}},{"musicResponsiveListItemRenderer":{"playlistItemData":{"videoId":"abcdefghijk"}}}]}`
	var data any
	json.Unmarshal([]byte(body), &data)
	songs := items(data, "song", 30)
	if len(songs) != 1 || songs[0].Title != "Song" || songs[0].Subtitle != "Artist" {
		t.Fatal(songs)
	}
}
func TestGuestLibraryRequiresLogin(t *testing.T) {
	if _, err := New(nil).Browse(context.Background(), "library", ""); err == nil {
		t.Fatal("guest accepted")
	}
}
func TestHTTPFailuresDoNotExposeResponse(t *testing.T) {
	m := New(nil)
	m.version = "fixture"
	m.HTTP.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 403, Body: io.NopCloser(strings.NewReader("private-token"))}, nil
	})
	_, err := m.Browse(context.Background(), "search", "song")
	if err == nil || strings.Contains(err.Error(), "private-token") {
		t.Fatal("unsafe error", err)
	}
}
func TestAccountHeadersAreSelected(t *testing.T) {
	m := New(store.Headers{"cookie": "fixture", "authorization": "SAPISIDHASH fixture", "x-goog-authuser": "2", "x-goog-pageid": "brand"})
	m.version = "fixture"
	m.HTTP.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.Header.Get("X-Goog-Authuser") != "2" || r.Header.Get("X-Goog-Pageid") != "brand" {
			t.Fatal("wrong account")
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"activeAccountHeaderRenderer":{"accountName":{"simpleText":"Selected"}}}`))}, nil
	})
	name, err := m.Account(context.Background())
	if err != nil || name != "Selected" {
		t.Fatal(name, err)
	}
}

func TestResolverUsesSelectedMusicAccount(t *testing.T) {
	for _, page := range []string{"", "selected-brand"} {
		t.Run(page, func(t *testing.T) {
			transport := credentialTransport{headers: store.Headers{"cookie": "fixture", "x-goog-authuser": "2", "x-goog-pageid": page}, version: "fixture-version", base: transportFunc(func(r *http.Request) (*http.Response, error) {
				if r.URL.Query().Get("authuser") != "2" {
					t.Fatal("wrong account index")
				}
				var body any
				json.NewDecoder(r.Body).Decode(&body)
				if text(path(body, "context", "client", "clientName")) != "WEB_REMIX" {
					t.Fatal("not a Music client")
				}
				if text(path(body, "context", "user", "onBehalfOfUser")) != page {
					t.Fatal("wrong brand account")
				}
				return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader("{}"))}, nil
			})}
			req, _ := http.NewRequest("POST", "https://www.youtube.com/youtubei/v1/player", strings.NewReader(`{"context":{"client":{"clientName":"ANDROID"},"user":{"onBehalfOfUser":"wrong-brand"}}}`))
			if _, err := transport.RoundTrip(req); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestBootstrapAndSearchUseBrowserContext(t *testing.T) {
	m := New(nil)
	m.HTTP.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if !strings.Contains(r.Header.Get("User-Agent"), "Chrome/") {
			return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader("no client config"))}, nil
		}
		body := `{"INNERTUBE_CLIENT_VERSION":"1.20261013.15.00"}`
		if r.Method == "POST" {
			var request any
			json.NewDecoder(r.Body).Decode(&request)
			if text(path(request, "context", "client", "clientVersion")) != "1.20261013.15.00" {
				t.Fatal("bootstrap version lost")
			}
			body = `{"musicResponsiveListItemRenderer":{"playlistItemData":{"videoId":"abcdefghijk"},"flexColumns":[{"musicResponsiveListItemFlexColumnRenderer":{"text":{"simpleText":"Fixture Song"}}}]}}`
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(body))}, nil
	})
	items, err := m.Browse(context.Background(), "search", "fixture")
	if err != nil || len(items) != 1 || items[0].Title != "Fixture Song" {
		t.Fatal(items, err)
	}
}
