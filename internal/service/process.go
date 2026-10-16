package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"time"

	"github.com/ttr1563/cmd-music-player/internal/store"
)

type ResolveRequest struct {
	ID      string        `json:"id"`
	Headers store.Headers `json:"headers"`
}
type ResolveResult struct {
	URL   string `json:"url,omitempty"`
	Error string `json:"error,omitempty"`
}

func ResolveProcess(ctx context.Context, headers store.Headers, id string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()
	executable, err := os.Executable()
	if err != nil {
		return "", err
	}
	body, err := json.Marshal(ResolveRequest{id, headers})
	if err != nil {
		return "", err
	}
	command := exec.CommandContext(ctx, executable, "--internal-resolver")
	command.Stdin = bytes.NewReader(body)
	defer clear(body)
	var result limitedBuffer
	command.Stdout = &result
	command.Stderr = io.Discard
	command.WaitDelay = 2 * time.Second
	err = command.Run()
	var response ResolveResult
	if json.Unmarshal(result.Bytes(), &response) != nil || err != nil || response.Error != "" || ValidateMediaURL(response.URL) != nil {
		return "", errors.New("音声を取得できません。認証状態またはサービス側の変更を確認してください。")
	}
	return response.URL, nil
}

type limitedBuffer struct{ bytes.Buffer }

func (b *limitedBuffer) Write(p []byte) (int, error) {
	if b.Len()+len(p) > 128000 {
		return 0, errors.New("応答サイズを超えました。")
	}
	return b.Buffer.Write(p)
}
func ResolverMain() int {
	var request ResolveRequest
	if json.NewDecoder(io.LimitReader(os.Stdin, 128001)).Decode(&request) != nil {
		json.NewEncoder(os.Stdout).Encode(ResolveResult{Error: "invalid_request"})
		return 1
	}
	url, err := New(request.Headers).Resolve(context.Background(), request.ID)
	if err != nil {
		json.NewEncoder(os.Stdout).Encode(ResolveResult{Error: "extract_failed"})
		return 1
	}
	json.NewEncoder(os.Stdout).Encode(ResolveResult{URL: url})
	return 0
}
