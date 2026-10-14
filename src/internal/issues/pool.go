package issues

import "sync"

// Workers is how many reads from GitHub run at once.
const Workers = 8

// parallel runs the reads on at most Workers goroutines and answers the
// error of the first read, in their order, that failed. Each read writes
// only its own result; no write to GitHub runs here.
func parallel(reads []func() error) error {
	errs := make([]error, len(reads))
	next := make(chan int)
	var wg sync.WaitGroup
	for range min(Workers, len(reads)) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for k := range next {
				errs[k] = reads[k]()
			}
		}()
	}
	for k := range reads {
		next <- k
	}
	close(next)
	wg.Wait()
	for _, err := range errs {
		if err != nil {
			return err
		}
	}
	return nil
}

// each runs read for every k below n on parallel and answers the results in
// their order.
func each[T any](n int, read func(k int) (T, error)) ([]T, error) {
	out := make([]T, n)
	reads := make([]func() error, n)
	for k := range n {
		reads[k] = func() (err error) {
			out[k], err = read(k)
			return err
		}
	}
	return out, parallel(reads)
}
