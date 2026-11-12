/* A frame cap for Kodi on Xvfb, loaded with LD_PRELOAD.
 *
 * Xvfb has no vblank and Kodi has no frame limiter of its own (xbmc
 * Application.cpp only sleeps when it renders nothing), so while anything moves
 * Kodi renders as fast as software GL allows and takes the cores it gets. This
 * wraps the buffer swap (GLX and EGL, whichever Kodi uses) and sleeps until
 * 1/cap s have passed since the last one. Animations in Kodi run on time, not
 * on frames, so they only get coarser; but the sleep holds Kodi's main loop, so
 * input and builtins wait up to one frame while something moves.
 *
 * The cap: KODI_FPS_CAP (the default), or the number in the file
 * KODI_FPS_CAP_FILE while it exists (a test that needs smooth frames writes it,
 * read again every CHECK_NS). 0 or nothing: no cap.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define CHECK_NS 250000000LL

static int initialised;
static long long default_ns;  /* from KODI_FPS_CAP, 0: no cap */
static const char *cap_file;
static long long frame_ns;
static long long checked_ns = -CHECK_NS;
static long long last_ns;

static long long now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static long long ns_of(int fps)
{
    return fps > 0 ? 1000000000LL / fps : 0;
}

static void read_cap(long long now)
{
    if (!initialised) {
        const char *cap = getenv("KODI_FPS_CAP");
        default_ns = ns_of(cap ? atoi(cap) : 0);
        cap_file = getenv("KODI_FPS_CAP_FILE");
        if (cap_file && !*cap_file)
            cap_file = NULL;
        frame_ns = default_ns;
        initialised = 1;
    }
    if (!cap_file || now - checked_ns < CHECK_NS)
        return;
    checked_ns = now;
    FILE *f = fopen(cap_file, "r");
    int fps;
    if (f && fscanf(f, "%d", &fps) == 1)
        frame_ns = ns_of(fps);
    else
        frame_ns = default_ns;
    if (f)
        fclose(f);
}

static void pace(void)
{
    long long now = now_ns();
    read_cap(now);
    if (!frame_ns)
        return;
    long long wait = last_ns + frame_ns - now;
    if (wait > 0 && wait <= frame_ns) {
        struct timespec ts = {wait / 1000000000LL, wait % 1000000000LL};
        nanosleep(&ts, NULL);
        now += wait;
    }
    last_ns = now;
}

void glXSwapBuffers(void *display, unsigned long drawable)
{
    static void (*real)(void *, unsigned long);
    if (!real)
        real = (void (*)(void *, unsigned long))dlsym(RTLD_NEXT, "glXSwapBuffers");
    pace();
    real(display, drawable);
}

unsigned int eglSwapBuffers(void *display, void *surface)
{
    static unsigned int (*real)(void *, void *);
    if (!real)
        real = (unsigned int (*)(void *, void *))dlsym(RTLD_NEXT, "eglSwapBuffers");
    pace();
    return real(display, surface);
}
