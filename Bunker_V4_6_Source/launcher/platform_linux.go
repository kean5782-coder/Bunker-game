package main

import (
	"fmt"
	"os/exec"
)

func openTarget(url string) error                      { return exec.Command("xdg-open", url).Start() }
func fatalMessage(s string)                            { fmt.Println(s) }
func prepareCommand(cmd *exec.Cmd)                     {}
func attachJob(cmd *exec.Cmd) uintptr                  { return 0 }
func closeJob(job uintptr)                             {}
func startTray(url string, stop func(), disabled bool) {}
