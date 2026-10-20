package main

import (
	"fmt"
	"github.com/ttr1563/cmd-music-player/internal/app"
	"github.com/ttr1563/cmd-music-player/internal/store"
	"os"
)

func main() {
	if err := app.Run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "fest:", store.SafeError(err))
		os.Exit(1)
	}
}
