// A small FIFO absorbs brief request bursts without opening extra connections.
const MAX_ACTIVE = 6;
const MAX_WAITING = 12;
const WAIT_MS = 2000;
type Release = () => void;
type Waiter = {resolve: (release: Release) => void; timer: ReturnType<typeof setTimeout>};

export class QueryAdmission {
  private active = 0;
  private waiting: Waiter[] = [];

  get activeCount(): number {return this.active;}

  acquire(): Promise<Release> {
    if (this.active < MAX_ACTIVE) {
      this.active++;
      return Promise.resolve(this.releaseHandle());
    }
    if (this.waiting.length >= MAX_WAITING) return Promise.reject(new Error('Service busy'));
    return new Promise((resolve, reject) => {
      const waiter: Waiter = {resolve, timer: setTimeout(() => {
        this.waiting.splice(this.waiting.indexOf(waiter), 1);
        reject(new Error('Service busy'));
      }, WAIT_MS)};
      this.waiting.push(waiter);
    });
  }

  private releaseHandle(): Release {
    let released = false;
    return () => {
      if (released) return;
      released = true;
      const next = this.waiting.shift();
      if (next) {
        clearTimeout(next.timer);
        // Transfer the occupied slot directly; new arrivals cannot overtake it.
        next.resolve(this.releaseHandle());
      } else {
        this.active--;
      }
    };
  }
}
