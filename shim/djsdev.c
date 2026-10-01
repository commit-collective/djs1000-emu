/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * djsdev: LD_PRELOAD shim that stands in for the DJS-1000's board devices so
 * EP113_Main_R runs under qemu-arm user mode.
 *
 * Every open() of a device in FAKE_DEVS gets either a descriptor on /dev/zero
 * ("zero": reads return zeros at once) or one end of a Unix socket pair
 * ("sock": pollable, so the app's epoll on it works). Each call is logged to
 * stderr with a "[djsdev]" prefix.
 *
 * The SPI links to the panel MCU (subucom_spi) and the codec (cdc_spi) follow
 * Pioneer's own driver, arch/arm/mach-mx6/subucom_spi.c in the GPL sources:
 * the app sets the frame to send with SUBUCOM_IOC_MESSAGE, starts a timer with
 * WR_TIMER_STATUS, and the driver exchanges a frame every TIMER_INTERVAL ms;
 * after each exchange the reply is kept, the device polls readable, and read()
 * returns the latest reply (rx_bytes long). Here a thread per device does the
 * ticking, and spi_reply() makes up the reply. New transmit frames are logged,
 * which shows the command sequence the app goes through.
 *
 * The app is built for glibc 2.13, soft-float ABI (arm-fsl-linux-gnueabi),
 * so this is compiled with -mfloat-abi=softfp, without the host's libc
 * headers, and linked against the device's own libc, libdl and libpthread
 * (from the assembled rootfs) so it records them as dependencies.
 *
 *   arm-linux-gnueabihf-gcc -O2 -fPIC -shared -nostdlib -mfloat-abi=softfp -marm \
 *       -o libdjsdev.so djsdev.c <rootfs>/lib/libdl.so.2 <rootfs>/lib/libc.so.6 \
 *       <rootfs>/lib/libpthread.so.0
 */
typedef unsigned int size_t;
typedef int ssize_t;
typedef unsigned long pthread_t;
typedef __builtin_va_list va_list;
#define va_start(v, l) __builtin_va_start(v, l)
#define va_arg(v, t) __builtin_va_arg(v, t)
#define va_end(v) __builtin_va_end(v)

#define RTLD_NEXT ((void *)-1l)
#define O_CREAT 0100
#define MAX_FD 1024
#define AF_UNIX 1
#define SOCK_STREAM 1
#define MSG_DONTWAIT 0x40

extern void *dlsym(void *handle, const char *name);
extern int socketpair(int domain, int type, int proto, int sv[2]);
extern ssize_t recv(int fd, void *buf, size_t n, int flags);
extern ssize_t send(int fd, const void *buf, size_t n, int flags);
extern int pthread_create(pthread_t *t, const void *attr, void *(*fn)(void *), void *arg);
extern int usleep(unsigned int us);
extern int fprintf(void *stream, const char *fmt, ...);
extern int strcmp(const char *a, const char *b);
extern int strncmp(const char *a, const char *b, size_t n);
extern char *strstr(const char *h, const char *n);
extern char *getenv(const char *name);
extern int mkfifo(const char *path, unsigned mode);
extern void *fopen(const char *path, const char *mode);
extern char *fgets(char *s, int n, void *stream);
extern int sscanf(const char *s, const char *fmt, ...);
extern size_t fwrite(const void *p, size_t size, size_t n, void *stream);
extern int fclose(void *stream);
extern int rename(const char *from, const char *to);
/* From libX11, which the app has loaded; never called in its child processes. */
extern int XSendEvent(void *dpy, unsigned long win, int propagate, long mask, void *event);
extern int XFlush(void *dpy);
extern void XLockDisplay(void *dpy);
extern void XUnlockDisplay(void *dpy);
extern void *memcpy(void *d, const void *s, size_t n);
extern int memcmp(const void *a, const void *b, size_t n);
extern void *memset(void *d, int c, size_t n);
extern void *stderr;

/* What each device is backed by. */
enum { DEV_ZERO, DEV_SOCK, DEV_SPI };

static const struct {
    const char *path;
    int kind;
} FAKE_DEVS[] = {
    { "/dev/backlight", DEV_ZERO },
    { "/dev/gpiodrv", DEV_ZERO },       /* polled ~500x/s */
    { "/dev/subucom_spi0.0", DEV_SPI }, /* panel MCU, update mode (the updater) */
    { "/dev/subucom_spi0.1", DEV_SPI }, /* panel MCU */
    { "/dev/cdc_spi2.0", DEV_SPI },     /* codec link, same ioctl set */
    { "/dev/din_midi", DEV_SOCK },
    { "/dev/ttymxc1", DEV_SOCK },
    { 0, 0 },
};
#define GPIODRV 1

/* SUBUCOM_IOC_* (subucom_spi.h): type 'p', nr below; _IOR reads, _IOW writes. */
#define SPI_FRAME 128
enum { NR_MESSAGE, NR_TIMER_STATUS, NR_TIMER_INTERVAL, NR_BITS_PER_WORD, NR_RX_BYTES,
       NR_UPDATE_DUMMY, NR_GPIO_LEVEL, NR_GPIO_NUM, NR_RD_ENDIAN, NR_WR_ENDIAN };

typedef struct {
    const char *name;
    int fd, peer;
    volatile int on;
    unsigned interval, rx_bytes, gpio_num;
    unsigned short bits_per_word;
    unsigned char endian;
    unsigned char tx[SPI_FRAME];   /* the frame the app asked to send */
    unsigned char rx[SPI_FRAME];   /* the reply read() returns */
    unsigned char last_logged[SPI_FRAME];
    unsigned long frames, tx_changes;
    int thread;
} Spi;

static const char *fake_name[MAX_FD];
static int fake_peer[MAX_FD];
static Spi *fake_spi[MAX_FD];
static Spi spis[4];
static int nspis;
static int gpio_logged;

static ssize_t (*real_read)(int, void *, size_t);
static ssize_t (*real_write)(int, const void *, size_t);

static int fake_match(const char *path)
{
    int i;

    if (!path || strncmp(path, "/dev/", 5)) {
        return -1;
    }
    for (i = 0; FAKE_DEVS[i].path; i++) {
        if (!strcmp(path, FAKE_DEVS[i].path)) {
            return i;
        }
    }
    return -1;
}

/* Hex dump of up to 128 bytes, 32 per line. */
static void dump(const char *tag, const unsigned char *p, unsigned int n)
{
    unsigned int i;

    if (n > SPI_FRAME) {
        n = SPI_FRAME;
    }
    for (i = 0; i < n; i++) {
        if (i % 32 == 0) {
            fprintf(stderr, "%s%s+%02x:", i ? "\n" : "", tag, i);
        }
        fprintf(stderr, " %02x", p[i]);
    }
    fprintf(stderr, "\n");
}

static const char *fake_fd(int fd)
{
    return fd >= 0 && fd < MAX_FD ? fake_name[fd] : 0;
}

/* CRC-16/X-25 (reflected 0x1021, init 0xFFFF, xorout 0xFFFF): what the app
 * puts at bytes 0x7C-0x7D of a panel frame, over bytes 0..0x7B. */
static unsigned short crc_x25(const unsigned char *p, unsigned n)
{
    unsigned short c = 0xFFFF;
    int b;

    while (n--) {
        c ^= *p++;
        for (b = 0; b < 8; b++) {
            c = c & 1 ? (c >> 1) ^ 0x8408 : c >> 1;
        }
    }
    return c ^ 0xFFFF;
}

/*
 * The panel's input state, as the frame the panel MCU sends
 * (didRecievePanelComData an address, buttons the app's routine, encoders
 * the app's routine):
 *
 *   0x00        identifier 0x01
 *   0x01-0x06   buttons, one bit each (46 button ids), plus
 *               byte 1 bit 1 = main encoder push, byte 6 bit 0 = a switch
 *   0x08-0x12   encoders 1-6: 16-bit counters (the app takes differences)
 *   0x14        encoder 0, the main rotary selector: 16-bit counter
 *   0x16-0x35   pads 0-15, first 16-bit value
 *   0x36-0x55   pads 0-15, second 16-bit value
 *   0x56-0x60   six 16-bit analogue values
 *   0x7C        CRC-16/X-25 of bytes 0..0x7B
 *
 * It is changed by keys in the app's window (XNextEvent below) and by
 * commands written to the pipe /tmp/djspanel (panel_thread).
 */
static volatile unsigned char panel[SPI_FRAME];
static const unsigned char ENC_OFFSET[7] = { 0x14, 0x08, 0x0A, 0x0C, 0x0E, 0x10, 0x12 };

static void panel_bit(unsigned byte, unsigned bit, int on)
{
    if (byte < 0x7C && bit < 8) {
        if (on) {
            panel[byte] |= 1u << bit;
        } else {
            panel[byte] &= ~(1u << bit);
        }
    }
}

static void panel_word(unsigned off, int value)
{
    if (off < 0x7B) {
        panel[off] = value & 0xFF;
        panel[off + 1] = (value >> 8) & 0xFF;
    }
}

static void panel_enc(unsigned n, int delta)
{
    if (n < 7) {
        unsigned off = ENC_OFFSET[n];

        panel_word(off, (short)(panel[off] | panel[off + 1] << 8) + delta);
    }
}

/*
 * A copy of the screen. The app draws only with XPutImage (an 800x480
 * image, 24 bits per pixel, in strips), so every blit is also copied here, and the "shot" command writes
 * the copy to /tmp/djsshot.raw: "DJS1", width, height (LE32 each), then
 * width*height*4 bytes of BGRX. tools/shot.py turns that into a PNG.
 */
#define SHOT_W 1024
#define SHOT_H 768
static unsigned char shot[SHOT_W * SHOT_H * 4];
static int shot_w, shot_h;
static void *x_dpy;          /* the app's display and window, for x_click() */
static unsigned long x_win;
static int power_ms;         /* ms since the first draw; -1 once the power line is released */

int XPutImage(void *dpy, unsigned long d, void *gc, void *image, int sx, int sy, int dx, int dy,
              unsigned w, unsigned h)
{
    static int (*real)(void *, unsigned long, void *, void *, int, int, int, int, unsigned, unsigned);
    const int *im = image;   /* XImage: width, height, xoffset, format, data, ..., [10] bytes_per_line, [11] bits_per_pixel */
    unsigned y;

    static int logged;

    if (!real) {
        real = dlsym(RTLD_NEXT, "XPutImage");
    }
    x_dpy = dpy;
    x_win = d;
    if (im && logged < 4) {
        logged++;
        fprintf(stderr, "[djsdev] XPutImage image %dx%d depth %d bpp %d stride %d, src %d,%d dst %d,%d size %ux%u\n",
                im[0], im[1], im[9], im[11], im[10], sx, sy, dx, dy, w, h);
    }
    if (im && (im[11] == 32 || im[11] == 24) && im[4] && sx >= 0 && sy >= 0 && dx >= 0 && dy >= 0 &&
        dx + (int)w <= SHOT_W && dy + (int)h <= SHOT_H && sx + (int)w <= im[0] && sy + (int)h <= im[1]) {
        const unsigned char *src = (const unsigned char *)im[4];
        unsigned bpp = im[11] / 8, x;

        /* The app's images are 800x480, 24 bits per pixel (B, G, R). */
        for (y = 0; y < h; y++) {
            const unsigned char *s = src + (sy + y) * im[10] + sx * bpp;
            unsigned char *o = shot + ((dy + y) * SHOT_W + dx) * 4;

            for (x = 0; x < w; x++, s += bpp, o += 4) {
                o[0] = s[0];
                o[1] = s[1];
                o[2] = s[2];
            }
        }
        if (dx + (int)w > shot_w) {
            shot_w = dx + w;
        }
        if (dy + (int)h > shot_h) {
            shot_h = dy + h;
        }
    }
    return real(dpy, d, gc, image, sx, sy, dx, dy, w, h);
}

/* The app's display and window, noted from its XPutImage calls, so that
 * "click" can send it a mouse press and release (the touchscreen arrives as
 * mouse events on the real unit too). Coordinates are those of a screenshot. */
static void x_click(int x, int y, int button)
{
    int ev[24];
    int press;

    if (!x_dpy) {
        return;
    }
    for (press = 1; press >= 0; press--) {
        memset(ev, 0, sizeof(ev));
        ev[0] = press ? 4 : 5;          /* ButtonPress / ButtonRelease */
        ev[2] = 1;                      /* send_event */
        ev[3] = (int)x_dpy;
        ev[4] = (int)x_win;             /* window */
        ev[8] = x;
        ev[9] = y;
        ev[10] = x;
        ev[11] = y;
        ev[12] = press ? 0 : 0x100 << (button - 1);   /* state: ButtonNMask on release */
        ev[13] = button;
        ev[14] = 1;                     /* same_screen */
        XLockDisplay(x_dpy);
        XSendEvent(x_dpy, x_win, 1, press ? 4 : 8, ev);   /* ButtonPressMask / ButtonReleaseMask */
        XFlush(x_dpy);
        XUnlockDisplay(x_dpy);
        usleep(120000);
    }
}

static void shot_write(void)
{
    void *f = fopen("/tmp/djsshot.tmp", "w");
    int hdr[2], y;

    if (!f) {
        return;
    }
    hdr[0] = shot_w;
    hdr[1] = shot_h;
    fwrite("DJS1", 1, 4, f);
    fwrite(hdr, 4, 2, f);
    for (y = 0; y < shot_h; y++) {
        fwrite(shot + y * SHOT_W * 4, 4, shot_w, f);
    }
    fclose(f);
    rename("/tmp/djsshot.tmp", "/tmp/djsshot.raw");
}

/* Commands, one per line, written to /tmp/djspanel (in the rootfs):
 *   bit <byte> <bit> <0|1>     set one button bit
 *   tap <byte> <bit>           press it for 150 ms
 *   enc <0-6> <delta>          turn an encoder
 *   pad <0-15> <a> <b>         a pad's two values
 *   word <offset> <value>      any 16-bit field
 *   shot                       write the screen copy to /tmp/djsshot.raw
 *   click <x> <y> [button]     mouse press and release at screenshot coordinates
 */
static void *panel_thread(void *arg)
{
    static const char path[] = "/tmp/djspanel";
    char line[128];
    void *f;

    (void)arg;
    mkfifo(path, 0666);
    f = fopen(path, "r+");
    if (!f) {
        fprintf(stderr, "[djsdev] no %s: panel commands off\n", path);
        return 0;
    }
    fprintf(stderr, "[djsdev] panel commands on %s\n", path);
    while (fgets(line, sizeof(line), f)) {
        int a = 0, b = 0, c = 0;

        if (!strncmp(line, "shot", 4)) {
            shot_write();
        } else if (sscanf(line, "click %i %i %i", &a, &b, &c) >= 2) {
            x_click(a, b, c ? c : 1);
        } else if (sscanf(line, "bit %i %i %i", &a, &b, &c) == 3) {
            panel_bit(a, b, c);
        } else if (sscanf(line, "tap %i %i", &a, &b) == 2) {
            panel_bit(a, b, 1);
            usleep(150000);
            panel_bit(a, b, 0);
        } else if (sscanf(line, "enc %i %i", &a, &b) == 2) {
            panel_enc(a, b);
        } else if (sscanf(line, "pad %i %i %i", &a, &b, &c) == 3 && a >= 0 && a < 16) {
            panel_word(0x16 + 2 * a, b);
            panel_word(0x36 + 2 * a, c);
        } else if (sscanf(line, "word %i %i", &a, &b) == 2) {
            panel_word(a, b);
        } else {
            fprintf(stderr, "[djsdev] panel command not understood: %s", line);
            continue;
        }
        fprintf(stderr, "[djsdev] panel: %s", line);
    }
    return 0;
}

/* Keys in the app's own window become panel input; the event still goes to
 * the app. X keycodes as WSLg sends them (evdev code + 8):
 *   Enter / keypad Enter   main encoder push (held while the key is down)
 *   , and .                main encoder one step back / forward
 *   F1-F6                  encoders 1-6 one step forward, with Shift back
 *   Escape / Backspace     BACK (byte 1 bit 3)
 *   C                      cancel in dialogs and sub-lists (byte 1 bit 2)
 *   1-8, Q-I               step keys 1-8 (byte 3 bits 0-7), 9-16 (byte 4)
 *   P                      PROJECT (byte 5 bit 5): opens and closes its menu
 *   L, X, -, S             LIVE SAMPLING, FX, TEMPO RANGE, SYNC
 *                          (byte 5 bits 6-7, byte 6 bits 4-5)
 * All found with tools/probe.py. Byte 5 bit 4 (button id 0) is tied to
 * power/standby: a press makes the app request standby ("transition
 * Standby!", tx byte 0x6C bit 1, the app's routine), and the panel is ignored
 * until it has been seen at 1.
 * (JUCE itself takes the arrows and Page Up/Down for its lists.)
 */
int XNextEvent(void *display, void *event)
{
    static int (*real)(void *, void *);
    const int *e = event;
    int r, type, code, shift;

    if (!real) {
        real = dlsym(RTLD_NEXT, "XNextEvent");
    }
    r = real(display, event);
    type = e[0];
    if (type != 2 /* KeyPress */ && type != 3 /* KeyRelease */) {
        return r;
    }
    shift = e[12] & 1;   /* XKeyEvent.state */
    code = e[13];        /* XKeyEvent.keycode */
    if (type == 2) {
        fprintf(stderr, "[djsdev] key %d (state 0x%x)\n", code, e[12]);
    }
    if (code == 36 || code == 104) {
        panel_bit(1, 1, type == 2);
    } else if (type == 2 && (code == 59 || code == 60)) {
        panel_enc(0, code == 60 ? 1 : -1);
    } else if (code == 9 || code == 22) {   /* Escape, Backspace: BACK */
        panel_bit(1, 3, type == 2);
    } else if (code == 54) {                /* C: cancel (dialogs, sub-lists) */
        panel_bit(1, 2, type == 2);
    } else if (code >= 10 && code <= 17) {  /* 1-8: step keys 1-8 */
        panel_bit(3, code - 10, type == 2);
    } else if (code >= 24 && code <= 31) {  /* Q-I: step keys 9-16 */
        panel_bit(4, code - 24, type == 2);
    } else if (code == 33) {                /* P: PROJECT (toggles the menu) */
        panel_bit(5, 5, type == 2);
    } else if (code == 46) {            /* L: LIVE SAMPLING */
        panel_bit(5, 6, type == 2);
    } else if (code == 53) {            /* X: FX */
        panel_bit(5, 7, type == 2);
    } else if (code == 20) {            /* -: TEMPO RANGE */
        panel_bit(6, 4, type == 2);
    } else if (code == 39) {            /* S: SYNC / MASTER (shows "No LINKED Players") */
        panel_bit(6, 5, type == 2);
    } else if (type == 2 && code >= 67 && code <= 72) {
        panel_enc(code - 66, shift ? -1 : 1);
    }
    return r;
}

/* The reply to an exchange: the panel's input state for the panel link, a
 * bare identifier for the codec link. */
static void spi_reply(Spi *s)
{
    unsigned char f[SPI_FRAME];
    unsigned short c;

    /* Built aside and copied in one go: the app may read() meanwhile. */
    memset(f, 0, SPI_FRAME);
    if (s->rx_bytes == SPI_FRAME) {
        memcpy(f, (const void *)panel, 0x7C);
    }
    f[0] = 0x01;
    c = crc_x25(f, 0x7C);
    f[0x7C] = c & 0xFF;
    f[0x7D] = c >> 8;
    memcpy(s->rx, f, SPI_FRAME);
}

/* The driver's timer: an exchange every interval ms, then wake the reader. */
static void *spi_thread(void *arg)
{
    Spi *s = arg;
    char one = 1;

    for (;;) {
        usleep((s->interval ? s->interval : 10) * 1000);
        if (!s->on) {
            continue;
        }
        /* Power/standby line (byte 5 bit 4): the app ignores the whole panel
         * until it has seen this bit go from 1 to 0, so it starts at 1 and
         * drops five seconds after the app first draws. From then on the app
         * keeps asking the panel for standby (tx byte 0x6C bit 1); nothing
         * answers that here. */
        if (s->rx_bytes == SPI_FRAME && power_ms >= 0) {
            if (!x_dpy) {
                panel_bit(5, 4, 1);
            } else if ((power_ms += s->interval ? s->interval : 10) >= 5000) {
                panel_bit(5, 4, 0);
                power_ms = -1;
                fprintf(stderr, "[djsdev] panel: power line released\n");
            }
        }
        spi_reply(s);
        if (s->frames++ < 3) {
            fprintf(stderr, "[djsdev] %s: reply #%lu\n", s->name, s->frames);
            dump("  rx", s->rx, s->rx_bytes ? s->rx_bytes : SPI_FRAME);
        }
        send(s->peer, &one, 1, MSG_DONTWAIT);
    }
    return 0;
}

static int open_common(const char *sym, const char *path, int flags, int mode)
{
    int (*real)(const char *, int, ...) = dlsym(RTLD_NEXT, sym);
    int i = fake_match(path);
    int sv[2];

    if (i < 0) {
        return real(path, flags, mode);
    }
    if (FAKE_DEVS[i].kind == DEV_ZERO) {
        sv[0] = real("/dev/zero", 2 /* O_RDWR */);
        sv[1] = -1;
    } else if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) < 0) {
        fprintf(stderr, "[djsdev] %s(%s): socketpair failed\n", sym, path);
        return -1;
    }
    if (sv[0] >= 0 && sv[0] < MAX_FD) {
        fake_name[sv[0]] = FAKE_DEVS[i].path;
        fake_peer[sv[0]] = sv[1];
        fake_spi[sv[0]] = 0;
        if (FAKE_DEVS[i].kind == DEV_SPI && nspis < 4) {
            Spi *s = &spis[nspis++];

            memset(s, 0, sizeof(*s));
            s->name = FAKE_DEVS[i].path;
            s->fd = sv[0];
            s->peer = sv[1];
            s->rx_bytes = SPI_FRAME;
            fake_spi[sv[0]] = s;
        }
    }
    fprintf(stderr, "[djsdev] %s(%s, 0x%x) = %d\n", sym, path, flags, sv[0]);
    return sv[0];
}

int open(const char *path, int flags, ...)
{
    int mode = 0;
    va_list ap;

    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    return open_common("open", path, flags, mode);
}

int open64(const char *path, int flags, ...)
{
    int mode = 0;
    va_list ap;

    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    return open_common("open64", path, flags, mode);
}

/* One SUBUCOM_IOC_* call on an emulated SPI link. */
static int spi_ioctl(Spi *s, unsigned long req, void *arg)
{
    unsigned nr = req & 0xFF, dir = (req >> 30) & 3;   /* 2 = _IOR, 1 = _IOW */

    switch (nr) {
    case NR_MESSAGE: {
        /* struct subucom_ioc_transfer { u8 multi_id, _reserved, part_id,
         * part_num; u32 bytes; u64 tx_buf; } -- only the first one is kept. */
        const unsigned char *t = arg;
        unsigned bytes = *(const unsigned *)(t + 4);
        const unsigned char *buf = (const unsigned char *)*(const unsigned *)(t + 8);

        if (bytes > SPI_FRAME) {
            bytes = SPI_FRAME;
        }
        memcpy(s->tx, buf, bytes);
        if (memcmp(s->tx, s->last_logged, SPI_FRAME)) {
            memcpy(s->last_logged, s->tx, SPI_FRAME);
            fprintf(stderr, "[djsdev] %s: new tx #%lu (multi %u, part %u/%u, %u bytes)\n",
                    s->name, ++s->tx_changes, t[0], t[2], t[3], bytes);
            dump("  tx", s->tx, bytes);
        }
        return 0;
    }
    case NR_TIMER_STATUS:
        if (dir == 2) {
            *(unsigned char *)arg = s->on;
        } else {
            s->on = *(unsigned char *)arg;
            fprintf(stderr, "[djsdev] %s: timer %s (interval %u ms, rx %u bytes)\n",
                    s->name, s->on ? "on" : "off", s->interval, s->rx_bytes);
            if (s->on && !s->thread) {
                static int panel_started;
                pthread_t t;

                s->thread = 1;
                pthread_create(&t, 0, spi_thread, s);
                if (!panel_started++) {
                    pthread_create(&t, 0, panel_thread, 0);
                }
            }
        }
        return 0;
    case NR_TIMER_INTERVAL:
        if (dir == 2) {
            *(unsigned *)arg = s->interval;
        } else {
            s->interval = *(unsigned *)arg;
        }
        return 0;
    case NR_BITS_PER_WORD:
        if (dir == 2) {
            *(unsigned short *)arg = s->bits_per_word ? s->bits_per_word : 8;
        } else {
            s->bits_per_word = *(unsigned short *)arg;
        }
        return 0;
    case NR_RX_BYTES:
        if (dir == 2) {
            *(unsigned *)arg = s->rx_bytes;
        } else {
            s->rx_bytes = *(unsigned *)arg;
            if (s->rx_bytes > SPI_FRAME) {
                s->rx_bytes = SPI_FRAME;
            }
        }
        return 0;
    case NR_GPIO_LEVEL:
        *(unsigned char *)arg = 1;
        return 0;
    case NR_GPIO_NUM:
        s->gpio_num = *(unsigned *)arg;
        return 0;
    case NR_RD_ENDIAN:
        *(unsigned char *)arg = s->endian;
        return 0;
    case NR_WR_ENDIAN:
        s->endian = *(unsigned char *)arg;
        return 0;
    }
    fprintf(stderr, "[djsdev] %s: ioctl 0x%lx not emulated\n", s->name, req);
    return 0;
}

int ioctl(int fd, unsigned long req, ...)
{
    int (*real)(int, unsigned long, void *) = dlsym(RTLD_NEXT, "ioctl");
    const char *dev = fake_fd(fd);
    void *arg;
    va_list ap;

    va_start(ap, req);
    arg = va_arg(ap, void *);
    va_end(ap);
    if (!dev) {
        return real(fd, req, arg);
    }
    if (fake_spi[fd] && ((req >> 8) & 0xFF) == 'p') {
        return spi_ioctl(fake_spi[fd], req, arg);
    }
    fprintf(stderr, "[djsdev] ioctl(%s, 0x%lx, %p) = 0\n", dev, req, arg);
    return 0;
}

ssize_t read(int fd, void *buf, size_t n)
{
    const char *dev = fake_fd(fd);
    Spi *s = dev ? fake_spi[fd] : 0;
    ssize_t r;

    if (!real_read) {
        real_read = dlsym(RTLD_NEXT, "read");
    }
    /* Like subucom_spi_read(): the latest reply, and clear "data ready". */
    if (s) {
        char drain[64];

        if (!s->on) {
            return 0;
        }
        while (recv(fd, drain, sizeof(drain), MSG_DONTWAIT) > 0) {
        }
        if (n > SPI_FRAME) {
            return -1;
        }
        memcpy(buf, s->rx, n);
        return n;
    }
    r = real_read(fd, buf, n);
    /* gpiodrv is polled constantly: log it once. */
    if (dev && (dev != FAKE_DEVS[GPIODRV].path || !gpio_logged++)) {
        fprintf(stderr, "[djsdev] read(%s, %u) = %d\n", dev, n, r);
    }
    return r;
}

ssize_t write(int fd, const void *buf, size_t n)
{
    const char *dev = fake_fd(fd);
    ssize_t r;

    if (!real_write) {
        real_write = dlsym(RTLD_NEXT, "write");
    }
    r = real_write(fd, buf, n);
    if (dev) {
        fprintf(stderr, "[djsdev] write(%s, %u) = %d\n", dev, n, r);
        dump("  wr", buf, n);
    }
    return r;
}

/* UDPRecvManager opens socket(AF_PACKET, SOCK_RAW, ETH_P_IP),
 * which needs CAP_NET_RAW; when it fails the app carries on with -1 and
 * crashes. Give it a socket that never receives anything, and
 * accept bind/setsockopt/ioctl on it. */
#define AF_PACKET 17
#define SOCK_DGRAM 2
static const char PACKET_NAME[] = "AF_PACKET socket";

int socket(int domain, int type, int proto)
{
    int (*real)(int, int, int) = dlsym(RTLD_NEXT, "socket");
    int sv[2];

    if (domain != AF_PACKET) {
        return real(domain, type, proto);
    }
    if (socketpair(AF_UNIX, SOCK_DGRAM, 0, sv) < 0) {
        return -1;
    }
    if (sv[0] < MAX_FD) {
        fake_name[sv[0]] = PACKET_NAME;
        fake_peer[sv[0]] = sv[1];
        fake_spi[sv[0]] = 0;
    }
    fprintf(stderr, "[djsdev] socket(AF_PACKET, %d, 0x%x) = %d (stand-in)\n", type, proto, sv[0]);
    return sv[0];
}

int bind(int fd, const void *addr, unsigned len)
{
    int (*real)(int, const void *, unsigned) = dlsym(RTLD_NEXT, "bind");

    return fake_fd(fd) == PACKET_NAME ? 0 : real(fd, addr, len);
}

int setsockopt(int fd, int level, int name, const void *val, unsigned len)
{
    int (*real)(int, int, int, const void *, unsigned) = dlsym(RTLD_NEXT, "setsockopt");

    return fake_fd(fd) == PACKET_NAME ? 0 : real(fd, level, name, val, len);
}

/* The board's sound card is an AK4452 DAC, opened as "hw:ak4452audio,N"
 * (0: headphones and input, 1: master). It goes to the ALSA PCM named by
 * DJSDEV_PCM instead, "null" (discard) by default. */
int snd_pcm_open(void **pcm, const char *name, int stream, int mode)
{
    int (*real)(void **, const char *, int, int) = dlsym(RTLD_NEXT, "snd_pcm_open");
    const char *to;
    int r;

    if (!name || !strstr(name, "ak4452audio")) {
        return real(pcm, name, stream, mode);
    }
    /* No inputs unless DJSDEV_CAPTURE=1: with capture on "null" the app's
     * audio thread copies from an unallocated channel and crashes. */
    if (stream == 1 /* SND_PCM_STREAM_CAPTURE */ && !getenv("DJSDEV_CAPTURE")) {
        fprintf(stderr, "[djsdev] snd_pcm_open(%s, capture) refused\n", name);
        return -19; /* -ENODEV */
    }
    to = getenv("DJSDEV_PCM");
    if (!to || !*to) {
        to = "null";
    }
    r = real(pcm, to, stream, mode);
    fprintf(stderr, "[djsdev] snd_pcm_open(%s, %s) -> %s = %d\n", name, stream ? "capture" : "playback", to, r);
    return r;
}

int close(int fd)
{
    int (*real)(int) = dlsym(RTLD_NEXT, "close");

    if (fake_fd(fd)) {
        fprintf(stderr, "[djsdev] close(%s)\n", fake_name[fd]);
        if (fake_spi[fd]) {
            fake_spi[fd]->on = 0;
        }
        fake_name[fd] = 0;
        fake_spi[fd] = 0;
        if (fake_peer[fd] >= 0) {
            real(fake_peer[fd]);
        }
    }
    return real(fd);
}
