"""Killable wall-clock limits for external work (Linux CI and macOS).

Socket timeouts do not bound DNS, extraction, retries or a whole article.
Use forked workers: no thread survives a phase deadline or blocks Python exit.
Workers return values; only the parent is allowed to update the archive.
"""
import multiprocessing
import time
from multiprocessing.connection import wait


def _invoke(pipe, fn, args):
    try:
        pipe.send((True, fn(*args)))
    except Exception as exc:
        pipe.send((False, type(exc).__name__))
    finally:
        pipe.close()


def bounded_results(fn, tasks, *, workers=1, timeout=30, wall=120):
    """Yield (task index, value, error); terminate overdue and unfinished work."""
    ctx = multiprocessing.get_context("fork")
    deadline = time.monotonic() + wall
    pending = iter(enumerate(tasks))
    active = {}
    exhausted = False

    def stop(conn):
        process, _, _ = active.pop(conn)
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join()
        conn.close()

    try:
        while time.monotonic() < deadline:
            while len(active) < workers and not exhausted:
                try:
                    index, args = next(pending)
                except StopIteration:
                    exhausted = True
                    break
                parent, child = ctx.Pipe(duplex=False)
                process = ctx.Process(target=_invoke, args=(child, fn, args), daemon=True)
                process.start()
                child.close()
                active[parent] = (process, index, min(deadline, time.monotonic() + timeout))
            if not active:
                break
            delay = max(0, min(v[2] for v in active.values()) - time.monotonic())
            for conn in wait(list(active), timeout=min(delay, 0.1)):
                _, index, _ = active[conn]
                try:
                    ok, value = conn.recv()
                except (EOFError, OSError):
                    ok, value = False, "worker exited"
                stop(conn)
                yield index, value if ok else None, None if ok else value
            for conn, (_, index, expires) in list(active.items()):
                if time.monotonic() >= expires:
                    stop(conn)
                    yield index, None, "wall-clock timeout"
    finally:
        for conn in list(active):
            stop(conn)


def bounded_call(fn, *args, timeout=30):
    if timeout <= 0:
        raise TimeoutError("phase budget exhausted")
    for _, value, error in bounded_results(fn, [args], timeout=timeout, wall=timeout):
        if error:
            raise TimeoutError(error)
        return value
    raise TimeoutError("phase budget exhausted")
