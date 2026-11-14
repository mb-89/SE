package host

import (
	"os"
	"strconv"
)

func platformProc(pid int) (string, error) {
	data, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	if err != nil {
		return "", err
	}
	return markFromStat(data)
}
