package issues

import "sync"

// Workers is how many reads from GitHub run at once: each is a request on
// one kept-alive client, not a process, so GitHub sets the bound, not the box.
const Workers = 96

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

// inflight runs reads as they come in, each at once on its own goroutine, at
// most Workers of them reading at a time, so a read that becomes known late,
// such as one for an issue on a list's second page, starts the moment it is
// known rather than when the whole list is. Wait answers the error of the
// first read, in the order they came, that failed. A read may add more.
type inflight struct {
	slots chan struct{}
	wg    sync.WaitGroup
	mu    sync.Mutex
	errs  []*error
}

func newGroup() *inflight { return &inflight{slots: make(chan struct{}, Workers)} }

// Go starts read.
func (g *inflight) Go(read func() error) {
	err := new(error)
	g.mu.Lock()
	g.errs = append(g.errs, err)
	g.mu.Unlock()
	g.wg.Add(1)
	go func() {
		defer g.wg.Done()
		g.slots <- struct{}{}
		defer func() { <-g.slots }()
		*err = read()
	}()
}

// Wait waits for every read started, those they started included.
func (g *inflight) Wait() error {
	g.wg.Wait()
	g.mu.Lock()
	defer g.mu.Unlock()
	for _, err := range g.errs {
		if *err != nil {
			return *err
		}
	}
	return nil
}
