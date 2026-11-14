package host

import "os"

// bootIDPath is where Linux names its boot.
const bootIDPath = "/proc/sys/kernel/random/boot_id"

func platformBoot() (string, error) {
	data, err := os.ReadFile(bootIDPath)
	if err != nil {
		return "", err
	}
	return bootFromProc(data)
}
