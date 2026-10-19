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
 * ticking, and spi_reply() makes up the reply. cdc_spi2.0 is the same driver
 * with 4-byte replies: the touch strip. New transmit frames are logged,
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
#define SOCK_DGRAM 2
#define MSG_DONTWAIT 0x40
#define MSG_NOSIGNAL 0x4000
#define AF_INET 2

extern void *dlsym(void *handle, const char *name);
extern int socketpair(int domain, int type, int proto, int sv[2]);
extern int listen(int fd, int backlog);
extern int shutdown(int fd, int how);
extern int accept(int fd, void *addr, unsigned *len);
extern int atoi(const char *s);
struct timespec { long tv_sec; long tv_nsec; };
extern int clock_gettime(int clock, struct timespec *ts);
int socket(int domain, int type, int proto);
int bind(int fd, const void *addr, unsigned len);
int setsockopt(int fd, int level, int name, const void *val, unsigned len);
int close(int fd);
extern ssize_t recv(int fd, void *buf, size_t n, int flags);
extern ssize_t send(int fd, const void *buf, size_t n, int flags);
extern int pthread_create(pthread_t *t, const void *attr, void *(*fn)(void *), void *arg);
extern int usleep(unsigned int us);
extern size_t strlen(const char *s);
extern int access(const char *path, int mode);
extern int system(const char *command);
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
extern size_t fread(void *p, size_t size, size_t n, void *stream);
extern int fseek(void *stream, long off, int whence);
/* From libX11, which the app has loaded; never called in its child processes. */
extern int XSendEvent(void *dpy, unsigned long win, int propagate, long mask, void *event);
extern int XFlush(void *dpy);
extern unsigned long XInternAtom(void *dpy, const char *name, int only_if_exists);
extern unsigned char XKeysymToKeycode(void *dpy, unsigned long keysym);
extern void XLockDisplay(void *dpy);
extern void XUnlockDisplay(void *dpy);
extern void *memcpy(void *d, const void *s, size_t n);
extern int memcmp(const void *a, const void *b, size_t n);
extern void *memset(void *d, int c, size_t n);
extern void *stderr;

/* What each device is backed by. */
enum { DEV_ZERO, DEV_SOCK, DEV_SPI, DEV_MSG };

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
    { "/proc/udev_usb1", DEV_MSG },     /* USB drive mounted / unmounted */
    { "/proc/udev_usbctn1", DEV_MSG },  /* USB port: connect / disconnect */
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
/*
 * The message queues /proc/udev_usb1 (a drive mounted / unmounted) and
 * /proc/udev_usbctn1 (something connected to / disconnected from the USB
 * port). In Pioneer's kernel (fs/proc/udev_usb.c, udev_usbctn.c) each is one
 * queue for the whole system: every write() is a message, kept until a read()
 * takes it, whoever wrote it and however late the reader opens; a message
 * beginning with '0' empties the queue. udev writes to them from a shell
 * (12-usb-memory-auto-mount.rules: "mount <path>", after the stick's
 * autoexec; 75-usb-caution.rules: "connect"), the app reads them
 * (UsbMountManager), and writes to the first itself ("do_umount
 * ..." for USB STOP). A new app started while a stick is in is told nothing
 * unless someone writes to the queue again.
 *
 * Here a queue is a file every process under this shim shares
 * (/tmp/djsdev-udev_usb1.q), each message preceded by a newline, with how
 * much of it the app has taken beside it (.pos). A process that opens the
 * queue only to write (udev's shell: busybox's echo writes from inside libc,
 * past write() here) gets that file itself, opened to append, a newline
 * already written. The app reads one end of a socket pair, so that it can
 * poll it; a thread in the app hands it the queue's new messages while it
 * has the queue open. run.sh empties the queues at each start, and init.sh
 * writes what udev would, for a stick in at power-on or plugged in later.
 */
#define USB_PATH "/media/usb1/sda1"
#define QUEUES 2
#define O_WRONLY 01
#define O_APPEND 02000

static const char *const QUEUE_DEV[QUEUES] = { "/proc/udev_usb1", "/proc/udev_usbctn1" };
static const char *const QUEUE_FILE[QUEUES] = { "/tmp/djsdev-udev_usb1.q", "/tmp/djsdev-udev_usbctn1.q" };
static const char *const QUEUE_POS[QUEUES] = { "/tmp/djsdev-udev_usb1.pos", "/tmp/djsdev-udev_usbctn1.pos" };
static int queue_fd[QUEUES] = { -1, -1 };     /* the app's reading descriptor */
static int queue_started[QUEUES];

static int queue_of(const char *dev)
{
    int q;

    for (q = 0; q < QUEUES; q++) {
        if (dev && !strcmp(dev, QUEUE_DEV[q])) {
            return q;
        }
    }
    return -1;
}

/* A message written by the app (through write()). */
static void queue_put(int q, const char *msg, size_t n)
{
    void *f;

    fprintf(stderr, "[djsdev] %s <- \"%.*s\"\n", QUEUE_DEV[q], (int)n, msg);
    if ((f = fopen(QUEUE_FILE[q], "a"))) {
        fwrite("\n", 1, 1, f);
        fwrite(msg, 1, n, f);
        fclose(f);
    }
}

/* Hands the app what has been written since it last read. A message
 * beginning with '0' empties the queue: neither it nor what was waiting
 * before it is handed on. */
static void queue_take(int q)
{
    char buf[4096], *m, *from, *end;
    int pos = 0, n;
    void *f;

    if ((f = fopen(QUEUE_POS[q], "r"))) {
        if (fgets(buf, sizeof(buf), f)) {
            pos = atoi(buf);
        }
        fclose(f);
    }
    if (!(f = fopen(QUEUE_FILE[q], "r"))) {
        return;
    }
    fseek(f, pos, 0);
    n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    if (n <= 0) {
        return;
    }
    buf[n] = 0;
    end = buf + n;
    from = buf;
    for (m = buf; m < end; m++) {
        if (*m == '\n' && m[1] == '0') {
            from = m + 1;
            while (from < end && *from != '\n') {
                from++;
            }
        }
    }
    for (m = from; m < end; m = from) {
        while (m < end && *m == '\n') {
            m++;
        }
        for (from = m; from < end && *from != '\n'; from++) {
        }
        if (from > m && queue_fd[q] >= 0) {
            send(fake_peer[queue_fd[q]], m, from - m, MSG_DONTWAIT);
            fprintf(stderr, "[djsdev] %s -> app \"%.*s\"\n", QUEUE_DEV[q], (int)(from - m), m);
        }
    }
    if ((f = fopen(QUEUE_POS[q], "w"))) {
        fprintf(f, "%d\n", pos + n);
        fclose(f);
    }
}

static void *queue_thread(void *arg)
{
    int q = (int)(long)arg;

    for (;;) {
        if (queue_fd[q] >= 0) {
            queue_take(q);
        }
        usleep(100000);
    }
    return 0;
}

static ssize_t (*real_read)(int, void *, size_t);
static ssize_t (*real_write)(int, const void *, size_t);

static int fake_match(const char *path)
{
    int i;

    if (!path || (strncmp(path, "/dev/", 5) && strncmp(path, "/proc/udev_", 11))) {
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
 * (the app's handlers of the panel's data, of its buttons and of its
 * encoders):
 *
 *   0x00        identifier 0x01
 *   0x01-0x06   buttons, one bit each (46 button ids), plus
 *               byte 1 bit 1 = main encoder push, byte 6 bit 0 = a switch
 *   0x08-0x12   encoders 1-6: 16-bit counters (the app takes differences)
 *   0x14        encoder 0, the main rotary selector: 16-bit counter
 *   0x16-0x35   pads 0-15, first 16-bit value: how hard, 0-1023. The app
 *               scales it by the pad's calibration (/root/data/
 *               PadCalibration.xml, 217-454: the reading where a hit
 *               begins); full velocity is near 840 with the one run.sh makes
 *   0x36-0x55   pads 0-15, second 16-bit value: above 59 while it is held
 *   0x56, 0x58  tempo slider: the centre's reference, and the position
 *               (0 the - end, 1023 the + end)
 *   0x5A        FX LEVEL/DEPTH, 0-1023
 *   0x5C        another 0-1023 reading (pot 0, linearised by a table)
 *   0x5E, 0x60  the screen's touch panel, raw x and y
 *   0x7C        CRC-16/X-25 of bytes 0..0x7B
 *
 * It is changed by keys in the app's window (XNextEvent below) and by
 * commands written to the pipe /tmp/djspanel (panel_thread).
 */
static volatile unsigned char panel[SPI_FRAME];
static volatile int strip_at = -1;      /* the touch strip: 0-127, or -1 when not touched */
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

/* A frame is taken whole (spi_reply), so a 16-bit value, or a pad's two,
 * must not be caught half written: the app would take a pad going to 900 as
 * a hit at 132. */
static volatile int panel_busy;

static void panel_lock(void)
{
    while (__sync_lock_test_and_set(&panel_busy, 1)) {
    }
}

static void panel_unlock(void)
{
    __sync_lock_release(&panel_busy);
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

        panel_lock();
        panel_word(off, (short)(panel[off] | panel[off + 1] << 8) + delta);
        panel_unlock();
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
static volatile int dirty_lock;      /* guards dirty_y0/y1 (a spinlock) */
static int dirty_y0 = SHOT_H, dirty_y1;   /* rows drawn since the deck was last sent them */
static void *x_dpy;          /* the app's display and window, for x_click() */
static unsigned long x_win;
static int power_ms;         /* DJSDEV_POWER_PULSE: ms since the first draw; -1 once released */

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
                o[3] = 0xFF;
            }
        }
        if (dx + (int)w > shot_w) {
            shot_w = dx + w;
        }
        if (dy + (int)h > shot_h) {
            shot_h = dy + h;
        }
        while (__sync_lock_test_and_set(&dirty_lock, 1)) {
        }
        if (dy < dirty_y0) {
            dirty_y0 = dy;
        }
        if (dy + (int)h > dirty_y1) {
            dirty_y1 = dy + h;
        }
        __sync_lock_release(&dirty_lock);
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

/* A key of a keyboard, pressed and released: "key <keysym>" (0xff08 is
 * BackSpace, 0xff51 Left, 0xff53 Right). The unit has no keyboard, but the
 * app's text fields take one. */
static void x_key(unsigned long keysym)
{
    int ev[24];
    int press;
    unsigned code;

    if (!x_dpy) {
        return;
    }
    XLockDisplay(x_dpy);
    code = XKeysymToKeycode(x_dpy, keysym);
    XUnlockDisplay(x_dpy);
    fprintf(stderr, "[djsdev] key %#lx: keycode %u\n", keysym, code);
    if (!code) {
        return;
    }
    for (press = 1; press >= 0; press--) {
        memset(ev, 0, sizeof(ev));
        ev[0] = press ? 2 : 3;          /* KeyPress / KeyRelease */
        ev[2] = 1;                      /* send_event */
        ev[3] = (int)x_dpy;
        ev[4] = (int)x_win;
        ev[13] = code;
        ev[14] = 1;                     /* same_screen */
        XLockDisplay(x_dpy);
        XSendEvent(x_dpy, x_win, 1, press ? 1 : 2, ev);   /* KeyPressMask / KeyReleaseMask */
        XFlush(x_dpy);
        XUnlockDisplay(x_dpy);
        usleep(60000);
    }
}

/* One step of a touch: kind 1 press, 2 move (held), 0 release. */
static void x_touch(int kind, int x, int y)
{
    int ev[24];

    if (!x_dpy) {
        return;
    }
    memset(ev, 0, sizeof(ev));
    ev[0] = kind == 1 ? 4 : kind == 2 ? 6 : 5;   /* ButtonPress / MotionNotify / ButtonRelease */
    ev[2] = 1;
    ev[3] = (int)x_dpy;
    ev[4] = (int)x_win;
    ev[8] = x;
    ev[9] = y;
    ev[10] = x;
    ev[11] = y;
    ev[12] = kind == 1 ? 0 : 0x100;              /* Button1Mask */
    ev[13] = kind == 2 ? 0 : 1;                  /* button (is_hint for a motion) */
    ev[14] = 1;
    XLockDisplay(x_dpy);
    /* ButtonPressMask / PointerMotionMask | Button1MotionMask | ButtonMotionMask / ButtonReleaseMask */
    XSendEvent(x_dpy, x_win, 1, kind == 1 ? 4 : kind == 2 ? 0x2140 : 8, ev);
    XFlush(x_dpy);
    XUnlockDisplay(x_dpy);
}

/* What the window's close button sends the app, for checking that the app
 * no longer acts on it (XNextEvent below). */
static void x_close(void)
{
    int ev[24];

    if (!x_dpy) {
        return;
    }
    memset(ev, 0, sizeof(ev));
    ev[0] = 33;                         /* ClientMessage */
    ev[2] = 1;
    ev[3] = (int)x_dpy;
    ev[4] = (int)x_win;
    XLockDisplay(x_dpy);
    ev[5] = (int)XInternAtom(x_dpy, "WM_PROTOCOLS", 0);
    ev[6] = 32;
    ev[7] = (int)XInternAtom(x_dpy, "WM_DELETE_WINDOW", 0);
    XSendEvent(x_dpy, x_win, 0, 0, ev);
    XFlush(x_dpy);
    XUnlockDisplay(x_dpy);
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
 *   byte <offset> <value>      any byte
 *   strip <0-127 | -1>         touch the strip there / let it go
 *   wmclose                    what the window's close button sends (ignored)
 *   shot                       write the screen copy to /tmp/djsshot.raw
 *   click <x> <y> [button]     mouse press and release at screenshot coordinates
 *   usb <0|1>                  unplug / plug the USB drive
 */
static void panel_command(const char *line)
{
    int a = 0, b = 0, c = 0;

    if (!strncmp(line, "shot", 4)) {
        shot_write();
    } else if (!strncmp(line, "wmclose", 7)) {
        x_close();
    } else if (sscanf(line, "touch %i %i %i", &a, &b, &c) == 3) {
        x_touch(a, b, c);
        if (a == 2) {
            return;     /* not logged: there are many */
        }
    } else if (sscanf(line, "key %i", &a) == 1) {
        x_key((unsigned long)a);
    } else if (sscanf(line, "click %i %i %i", &a, &b, &c) >= 2) {
        x_click(a, b, c ? c : 1);
    } else if (sscanf(line, "usb %i", &a) == 1) {
        /* A stick plugged in or out: what udev does, which writes to the
         * queues (scripts/guest/init.sh). */
        if (a && access(USB_PATH, 0)) {
            fprintf(stderr, "[djsdev] usb: no %s\n", USB_PATH);
        } else {
            system(a ? "/bin/sh /opt/djsemu/init.sh plug" : "/bin/sh /opt/djsemu/init.sh unplug");
        }
    } else if (sscanf(line, "bit %i %i %i", &a, &b, &c) == 3) {
        panel_bit(a, b, c);
    } else if (sscanf(line, "tap %i %i", &a, &b) == 2) {
        panel_bit(a, b, 1);
        usleep(150000);
        panel_bit(a, b, 0);
    } else if (sscanf(line, "enc %i %i", &a, &b) == 2) {
        panel_enc(a, b);
    } else if (sscanf(line, "pad %i %i %i", &a, &b, &c) == 3 && a >= 0 && a < 16) {
        panel_lock();
        panel_word(0x16 + 2 * a, b);
        panel_word(0x36 + 2 * a, c);
        panel_unlock();
    } else if (sscanf(line, "strip %i", &a) == 1) {
        strip_at = a < 0 ? -1 : a > 127 ? 127 : a;
        return;         /* not logged: a finger sliding sends many */
    } else if (sscanf(line, "byte %i %i", &a, &b) == 2 && a >= 0 && a < 0x7C) {
        panel[a] = b;
    } else if (sscanf(line, "word %i %i", &a, &b) == 2) {
        panel_lock();
        panel_word(a, b);
        panel_unlock();
    } else {
        fprintf(stderr, "[djsdev] panel command not understood: %s", line);
        return;
    }
    fprintf(stderr, "[djsdev] panel: %s", line);
}

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
        panel_command(line);
    }
    return 0;
}

/*
 * The virtual deck's link (app/virtual_djs.py): one TCP client at a time on
 * 127.0.0.1:$DJSDEV_PORT (7310). It sends the same command lines as the pipe
 * takes, and is sent, each with an 8-byte header:
 *
 *   'S' 0, y, rows, width (LE16 each)   then rows*width*4 bytes of BGRX:
 *                                       rows of the screen copy that changed
 *   'L' and 7 zeros                     then the 128-byte frame the app sends
 *                                       the panel (the lamps), when it changes
 *   'A' n, frames (LE16), 4 zeros       then frames*8 bytes: output n (0 master,
 *                                       1 headphones), stereo float32 at 44.1 kHz
 *
 * Besides command lines the deck sends the input's sound: the line
 * "in <frames>" and then frames*4 bytes, stereo 16-bit at 44.1 kHz.
 *
 * A new client is sent the whole screen and the current frame. Up to DECKS
 * clients are served at once (the deck, and a script watching beside it);
 * each is sent everything, and commands are taken from all.
 */
#define DECKS 4                         /* clients at a time */
static volatile int deck_fd[DECKS] = { -1, -1, -1, -1 };
static volatile int deck_fresh[DECKS];  /* just connected: owed the whole screen */

/* The two outputs (0 master, 1 headphones), as the app writes them: stereo
 * float frames in rings the audio thread fills (audio_put) and the deck
 * link's sender empties. And the input: stereo 16-bit frames the deck sends,
 * which the app's read takes (snd_pcm_readi). */
#define RING_FRAMES 16384               /* a power of two; 370 ms */
static float ring[2][RING_FRAMES * 2];
static volatile unsigned ring_w[2], ring_r[2];
static short in_ring[RING_FRAMES * 2];
static volatile unsigned in_w, in_r;
static Spi *panel_spi;

static int deck_send(int fd, const void *buf, unsigned n)
{
    const char *p = buf;

    while (n) {
        ssize_t r = send(fd, p, n, MSG_NOSIGNAL);

        if (r <= 0) {
            return -1;
        }
        p += r;
        n -= r;
    }
    return 0;
}

/* One message to client i; a client that cannot be sent to is dropped (its
 * reader, woken by the shutdown, closes it). */
static void deck_msg(int i, const unsigned char *hdr, const void *body, unsigned n)
{
    int fd = deck_fd[i];

    if (fd >= 0 && (deck_send(fd, hdr, 8) || deck_send(fd, body, n))) {
        deck_fd[i] = -1;
        shutdown(fd, 2);
    }
}

static void deck_screen(int i, int y0, int y1)
{
    unsigned char hdr[8];
    int y;

    if (y1 <= y0 || !shot_w) {
        return;
    }
    memset(hdr, 0, sizeof(hdr));
    hdr[0] = 'S';
    hdr[2] = y0 & 0xFF;
    hdr[3] = y0 >> 8;
    hdr[4] = (y1 - y0) & 0xFF;
    hdr[5] = (y1 - y0) >> 8;
    hdr[6] = shot_w & 0xFF;
    hdr[7] = shot_w >> 8;
    deck_msg(i, hdr, shot + y0 * SHOT_W * 4, shot_w * 4);
    for (y = y0 + 1; y < y1 && deck_fd[i] >= 0; y++) {
        if (deck_send(deck_fd[i], shot + y * SHOT_W * 4, shot_w * 4)) {
            shutdown(deck_fd[i], 2);
            deck_fd[i] = -1;
        }
    }
}

static void *deck_sender(void *arg)
{
    static unsigned char last[SPI_FRAME];
    unsigned char hdr[8], tx[SPI_FRAME];
    int i, y0, y1, ch, any, changed;
    unsigned tick;

    (void)arg;
    for (tick = 0;; tick++) {
        usleep(5000);
        for (any = 0, i = 0; i < DECKS; i++) {
            any |= deck_fd[i] >= 0;
        }
        if (!any) {
            ring_r[0] = ring_w[0];
            ring_r[1] = ring_w[1];
            continue;
        }
        /* Sound every 5 ms, in runs that do not wrap. */
        for (ch = 0; ch < 2; ch++) {
            while (ring_r[ch] != ring_w[ch]) {
                unsigned r = ring_r[ch], at = r % RING_FRAMES, n = ring_w[ch] - r;

                if (n > RING_FRAMES) {          /* overrun: keep the newest */
                    ring_r[ch] = ring_w[ch] - RING_FRAMES / 2;
                    continue;
                }
                if (n > RING_FRAMES - at) {
                    n = RING_FRAMES - at;
                }
                if (n > 4096) {
                    n = 4096;
                }
                memset(hdr, 0, sizeof(hdr));
                hdr[0] = 'A';
                hdr[1] = ch;
                hdr[2] = n & 0xFF;
                hdr[3] = n >> 8;
                /* Where these frames are in the output (frames written to it
                 * since the start, low 32 bits): both outputs are written
                 * block for block, so equal positions are the same moment. */
                hdr[4] = r & 0xFF;
                hdr[5] = (r >> 8) & 0xFF;
                hdr[6] = (r >> 16) & 0xFF;
                hdr[7] = r >> 24;
                for (i = 0; i < DECKS; i++) {
                    if (!deck_fresh[i]) {
                        deck_msg(i, hdr, ring[ch] + at * 2, n * 8);
                    }
                }
                ring_r[ch] = r + n;
            }
        }
        for (any = 0, i = 0; i < DECKS; i++) {
            any |= deck_fresh[i];
        }
        if (tick % 3 && !any) {             /* screen and lamps every 15 ms */
            continue;
        }
        while (__sync_lock_test_and_set(&dirty_lock, 1)) {
        }
        y0 = dirty_y0;
        y1 = dirty_y1;
        dirty_y0 = SHOT_H;
        dirty_y1 = 0;
        __sync_lock_release(&dirty_lock);
        changed = 0;
        if (panel_spi) {
            memcpy(tx, panel_spi->tx, SPI_FRAME);
            changed = memcmp(tx, last, SPI_FRAME) != 0;
            memcpy(last, tx, SPI_FRAME);
        }
        memset(hdr, 0, sizeof(hdr));
        hdr[0] = 'L';
        for (i = 0; i < DECKS; i++) {
            if (deck_fd[i] < 0) {
                continue;
            }
            if (deck_fresh[i]) {
                deck_fresh[i] = 0;
                deck_screen(i, 0, shot_h);
                if (panel_spi) {
                    deck_msg(i, hdr, tx, SPI_FRAME);
                }
            } else {
                deck_screen(i, y0, y1);
                if (changed) {
                    deck_msg(i, hdr, tx, SPI_FRAME);
                }
            }
        }
    }
    return 0;
}

/* One client's commands, and the input's sound after an "in" line. */
static void *deck_reader(void *arg)
{
    int i = (int)(long)arg, fd = deck_fd[i], frames, k;
    char buf[2048], line[128];
    unsigned n = 0, raw = 0;            /* raw: bytes of input sound still to come */
    unsigned char half[4];

    for (;;) {
        ssize_t r = recv(fd, buf, sizeof(buf), 0);

        if (r <= 0) {
            break;
        }
        for (k = 0; k < r; k++) {
            if (raw) {
                half[(4 - raw % 4) % 4] = buf[k];
                if (--raw % 4 == 0) {
                    unsigned w = in_w;

                    in_ring[(w % RING_FRAMES) * 2] = (short)(half[0] | half[1] << 8);
                    in_ring[(w % RING_FRAMES) * 2 + 1] = (short)(half[2] | half[3] << 8);
                    in_w = w + 1;
                }
                continue;
            }
            if (n < sizeof(line) - 2) {
                line[n++] = buf[k];
            }
            if (buf[k] == '\n') {
                line[n] = 0;
                if (sscanf(line, "in %i", &frames) == 1 && frames > 0 && frames <= 65536) {
                    raw = frames * 4;
                } else {
                    panel_command(line);
                }
                n = 0;
            }
        }
    }
    if (deck_fd[i] == fd) {
        deck_fd[i] = -1;
    }
    usleep(100000);          /* let the sender finish with it */
    close(fd);
    fprintf(stderr, "[djsdev] deck link: closed\n");
    return 0;
}

static void *deck_server(void *arg)
{
    const char *e = getenv("DJSDEV_PORT");
    int port = e && *e ? atoi(e) : 7310, one = 1, ls, fd, i;
    unsigned char addr[16];
    pthread_t t;

    (void)arg;
    if (port <= 0) {
        return 0;
    }
    memset(addr, 0, sizeof(addr));
    addr[0] = AF_INET;
    addr[2] = port >> 8;
    addr[3] = port & 0xFF;
    addr[4] = 127;
    addr[7] = 1;
    ls = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(ls, 1 /* SOL_SOCKET */, 2 /* SO_REUSEADDR */, &one, sizeof(one));
    if (ls < 0 || bind(ls, addr, sizeof(addr)) < 0 || listen(ls, DECKS) < 0) {
        fprintf(stderr, "[djsdev] deck link: cannot listen on 127.0.0.1:%d\n", port);
        return 0;
    }
    fprintf(stderr, "[djsdev] deck link on 127.0.0.1:%d\n", port);
    pthread_create(&t, 0, deck_sender, 0);
    for (;;) {
        fd = accept(ls, 0, 0);
        if (fd < 0) {
            usleep(100000);
            continue;
        }
        for (i = 0; i < DECKS && deck_fd[i] >= 0; i++) {
        }
        if (i == DECKS) {
            close(fd);
            continue;
        }
        setsockopt(fd, 6 /* IPPROTO_TCP */, 1 /* TCP_NODELAY */, &one, sizeof(one));
        fprintf(stderr, "[djsdev] deck link: connected\n");
        deck_fresh[i] = 1;
        deck_fd[i] = fd;
        pthread_create(&t, 0, deck_reader, (void *)(long)i);
    }
    return 0;
}

/* Keys in the app's own window become panel input; the event still goes to
 * the app. X keycodes as WSLg sends them (evdev code + 8):
 *   Enter / keypad Enter   main encoder push (held while the key is down)
 *   , and .                main encoder one step back / forward
 *   F1-F6                  encoders 1-6 one step forward, with Shift back
 *   Escape / Backspace     BACK (byte 1 bit 2)
 *   H                      HOME (byte 1 bit 3)
 *   Space, B, N            PLAY/PAUSE, STOP, REC (byte 2 bits 3, 2, 1)
 *   1-8, Q-I               step keys 1-8 (byte 3 bits 0-7), 9-16 (byte 4)
 *   P                      PROJECT (byte 5 bit 5): opens and closes its menu
 *   L, X, -, S             LIVE SAMPLING, FX, TEMPO RANGE, SYNC
 *                          (byte 5 bits 6-7, byte 6 bits 4-5)
 * All found with tools/probe.py. Byte 5 bit 4 (button id 0) is tied to
 * power/standby: a press and release puts the app in standby ("transition
 * Standby!", tx byte 0x6C bit 1). No key is bound to it.
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
    for (;;) {
        r = real(display, event);
        type = e[0];
        /* Closing the app's window would make it quit, and it does not get
         * as far as exiting: it is left half shut down, its screen frozen.
         * The unit has no window to close, so the request is dropped. */
        if (type == 33 /* ClientMessage */ && e[6] == 32 &&
            (unsigned long)e[7] == XInternAtom(display, "WM_DELETE_WINDOW", 1)) {
            fprintf(stderr, "[djsdev] window close ignored: stop the emulator instead\n");
            continue;
        }
        break;
    }
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
        panel_bit(1, 2, type == 2);
    } else if (code == 43) {                /* H: HOME */
        panel_bit(1, 3, type == 2);
    } else if (code == 65) {                /* Space: PLAY/PAUSE */
        panel_bit(2, 3, type == 2);
    } else if (code == 56) {                /* B: STOP */
        panel_bit(2, 2, type == 2);
    } else if (code == 57) {                /* N: REC */
        panel_bit(2, 1, type == 2);
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

/* The touch strip, which is what the second link (/dev/cdc_spi2.0) carries:
 * a 4-byte reply whose first byte is 127 less the position and whose second
 * has bit 7 set while the strip is touched (CdcManager's read). */
static int strip_last;

/* The reply to an exchange: the panel's input state for the panel link, the
 * strip's for the other. */
static void spi_reply(Spi *s)
{
    unsigned char f[SPI_FRAME];
    unsigned short c;
    int at = strip_at;

    /* Built aside and copied in one go: the app may read() meanwhile. */
    memset(f, 0, SPI_FRAME);
    if (s->rx_bytes != SPI_FRAME) {
        if (at >= 0) {
            strip_last = at & 0x7F;
        }
        f[0] = 0x7F - strip_last;
        f[1] = at >= 0 ? 0x80 : 0;
        memcpy(s->rx, f, SPI_FRAME);
        return;
    }
    panel_lock();
    memcpy(f, (const void *)panel, 0x7C);
    panel_unlock();
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
        /* Power/standby key (byte 5 bit 4), only with DJSDEV_POWER_PULSE=1:
         * held from the start and released five seconds after the app first
         * draws, which puts the app in standby (it then keeps asking the
         * panel for it, tx byte 0x6C bit 1; nothing answers that here). This
         * was the way to wake the panel while the audio device failed to
         * open; it is kept for looking at standby itself. */
        if (s->rx_bytes == SPI_FRAME && power_ms >= 0 && getenv("DJSDEV_POWER_PULSE")) {
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
    /* Writing only to a message queue: the queue's file (see queue_take()). */
    if (FAKE_DEVS[i].kind == DEV_MSG && (flags & 3) == O_WRONLY && queue_of(FAKE_DEVS[i].path) >= 0) {
        int fd = real(QUEUE_FILE[queue_of(FAKE_DEVS[i].path)], O_WRONLY | O_APPEND | O_CREAT, 0644);

        if (!real_write) {
            real_write = dlsym(RTLD_NEXT, "write");
        }
        if (fd >= 0) {
            real_write(fd, "\n", 1);
        }
        return fd;
    }
    if (FAKE_DEVS[i].kind == DEV_ZERO) {
        sv[0] = real("/dev/zero", 2 /* O_RDWR */);
        sv[1] = -1;
    } else if (socketpair(AF_UNIX, FAKE_DEVS[i].kind == DEV_MSG ? SOCK_DGRAM : SOCK_STREAM, 0, sv) < 0) {
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
            if (strstr(s->name, "subucom_spi0.1")) {
                panel_spi = s;
                /* The tempo slider at its centre: its reading (0x58) and the
                 * centre's reference (0x56). */
                panel_word(0x56, 512);
                panel_word(0x58, 512);
            }
        }
    }
    fprintf(stderr, "[djsdev] %s(%s, 0x%x) = %d\n", sym, path, flags, sv[0]);
    /* A reader of a message queue (the app; udev's shell only writes). */
    if (FAKE_DEVS[i].kind == DEV_MSG && (flags & 3) != 1 && sv[0] >= 0 && sv[0] < MAX_FD) {
        int q = queue_of(FAKE_DEVS[i].path);

        if (q >= 0) {
            pthread_t t;

            queue_fd[q] = sv[0];
            if (!queue_started[q]++) {
                pthread_create(&t, 0, queue_thread, (void *)(long)q);
            }
        }
    }
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
                    pthread_create(&t, 0, deck_server, 0);
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
    /* WirelessLanMonitor::checkEtherLanConnection asks the Ethernet
     * driver, on "eth0", with the device-private requests 0x89fc, 0x89fd and
     * 0x89fe (the last answers through the ifreq's data pointer: non-zero
     * when the cable is in; NetworkManager sets up with 0x89ff). The host kernel cannot take those (the app
     * sees ENOTTY and thinks there is no cable, and the Pro DJ Link stack
     * stays down): the cable is in. */
    if (!dev && (req == 0x89fc || req == 0x89fd || req == 0x89fe || req == 0x89ff) && arg &&
        !strncmp((const char *)arg, "eth0", 5)) {
        int *state = *(int **)((char *)arg + 16);

        if (req == 0x89fe && state) {
            *state = 1;
        }
        return 0;
    }
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
    /* A message for the queue, from whichever process. */
    if (dev && queue_of(dev) >= 0) {
        queue_put(queue_of(dev), buf, n);
        return n;
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
 * crashes. Give it a socket instead, and accept bind/setsockopt/
 * ioctl on it. What arrives on it is Pro DJ Link, as the app sees it on a
 * unit: the broadcasts on UDP 50000 (a deck announcing itself), 50001
 * (beats) and 50002 (a deck's status), which this listens to on the host
 * side with ordinary sockets (sharing the ports) and hands to every such
 * socket as the Ethernet frame a raw packet socket would have given it
 * (without its header for a datagram socket; zero MAC, the sender's IP and port, the datagram as it came). So decks on
 * the host's network, or on its loopback (a program sending fake ones: the
 * djs1000-mods project's tests/fakedecks.py), are seen by the app, and by
 * anything else in it that reads the network. Only receiving: the app does
 * not announce itself. */
#define AF_PACKET 17
static const char PACKET_NAME[] = "AF_PACKET socket";
#define PACKET_FDS 8
static volatile int packet_fd[PACKET_FDS];      /* our end of each stand-in, or 0 */
static volatile int packet_cooked[PACKET_FDS];  /* SOCK_DGRAM: no link header */
/* Which of the app's sockets are bound to the Pro DJ Link ports (50000-50002),
 * and what arrives on them: each kind of packet (port, type byte at 0x0a,
 * size class) is logged once, so that the log says what the app was given. */
static int link_port[MAX_FD];
static unsigned char link_seen[3][256][4];
static int link_started;
static unsigned char own_ip[4];
static int own_ip_known;

extern ssize_t recvfrom(int fd, void *buf, size_t n, int flags, void *addr, unsigned *len);

static unsigned ip_checksum(const unsigned char *h, int n)
{
    unsigned sum = 0;
    int i;

    for (i = 0; i + 1 < n; i += 2) {
        sum += h[i] << 8 | h[i + 1];
    }
    while (sum >> 16) {
        sum = (sum & 0xffff) + (sum >> 16);
    }
    return ~sum & 0xffff;
}

/* A datagram as an Ethernet frame: broadcast to a zero MAC, IPv4 to
 * 255.255.255.255, UDP without a checksum. */
static int link_frame(unsigned char *out, int port, const unsigned char *from_ip,
                      const unsigned char *from_port, const unsigned char *data, int n)
{
    int ip_len = 20 + 8 + n, i;
    unsigned sum;

    for (i = 0; i < 6; i++) {
        out[i] = 0xff;
        out[6 + i] = 0;
    }
    out[11] = 0x01;
    out[12] = 0x08;
    out[13] = 0x00;
    out[14] = 0x45;
    out[15] = 0;
    out[16] = ip_len >> 8;
    out[17] = ip_len;
    out[18] = out[19] = out[20] = out[21] = 0;
    out[22] = 64;
    out[23] = 17;
    out[24] = out[25] = 0;
    for (i = 0; i < 4; i++) {
        out[26 + i] = from_ip[i];
        out[30 + i] = 0xff;
    }
    sum = ip_checksum(out + 14, 20);
    out[24] = sum >> 8;
    out[25] = sum;
    out[34] = from_port[0];
    out[35] = from_port[1];
    out[36] = port >> 8;
    out[37] = port;
    out[38] = (8 + n) >> 8;
    out[39] = 8 + n;
    out[40] = out[41] = 0;
    for (i = 0; i < n; i++) {
        out[42 + i] = data[i];
    }
    return 14 + ip_len;
}

static void *link_listener(void *arg)
{
    int port = (int)(long)arg, one = 1, fd, i;
    unsigned char sa[16], buf[1400], frame[1500];

    fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        return 0;
    }
    setsockopt(fd, 1 /* SOL_SOCKET */, 2 /* SO_REUSEADDR */, &one, sizeof(one));
    setsockopt(fd, 1, 15 /* SO_REUSEPORT */, &one, sizeof(one));
    for (i = 0; i < 16; i++) {
        sa[i] = 0;
    }
    sa[0] = AF_INET;
    sa[2] = port >> 8;
    sa[3] = port;
    if (bind(fd, sa, sizeof(sa)) != 0) {
        fprintf(stderr, "[djsdev] Pro DJ Link: cannot listen on UDP %d\n", port);
        return 0;
    }
    link_port[fd] = 0;                  /* ours: not what the app is given */
    fprintf(stderr, "[djsdev] Pro DJ Link: listening on UDP %d\n", port);
    for (;;) {
        unsigned alen = sizeof(sa);
        int n = recvfrom(fd, buf, sizeof(buf), 0, sa, &alen), len;
        static int first[3];

        if (n <= 0) {
            usleep(100000);
            continue;
        }
        if (!first[port - 50000]++) {
            fprintf(stderr, "[djsdev] Pro DJ Link: first datagram on UDP %d, %d bytes\n", port, n);
        }
        /* What comes from the unit's own address is its own broadcast looping
         * back, which a packet socket on a real network would not be given as an
         * incoming frame (the unit would be a player of its own network). Decks
         * are on other addresses: 127.0.0.n, or addresses of the host's network
         * of their own. (If the unit's address is not known: whatever is not
         * from the loopback.) */
        if (own_ip_known ? (sa[4] == own_ip[0] && sa[5] == own_ip[1] && sa[6] == own_ip[2]
                            && sa[7] == own_ip[3])
                         : sa[4] != 127) {
            static int dropped[3];

            if (!dropped[port - 50000]++) {
                fprintf(stderr, "[djsdev] Pro DJ Link: not passing the unit's own datagrams (UDP %d, from %d.%d.%d.%d)\n",
                        port, sa[4], sa[5], sa[6], sa[7]);
            }
            continue;
        }
        len = link_frame(frame, port, sa + 4, sa + 2, buf, n);
        for (i = 0; i < PACKET_FDS; i++) {
            if (packet_fd[i]) {
                if (packet_cooked[i]) {
                    send(packet_fd[i], frame + 14, len - 14, MSG_DONTWAIT);
                } else {
                    send(packet_fd[i], frame, len, MSG_DONTWAIT);
                }
            }
        }
    }
}

static void find_own_ip(void)
{
    unsigned char ifr[40];
    int fd = socket(AF_INET, SOCK_DGRAM, 0), i;

    if (fd < 0) {
        return;
    }
    for (i = 0; i < 40; i++) {
        ifr[i] = 0;
    }
    ifr[0] = 'e';
    ifr[1] = 't';
    ifr[2] = 'h';
    ifr[3] = '0';
    if (ioctl(fd, 0x8915 /* SIOCGIFADDR */, ifr) == 0) {
        for (i = 0; i < 4; i++) {
            own_ip[i] = ifr[20 + i];
        }
        own_ip_known = 1;
        fprintf(stderr, "[djsdev] Pro DJ Link: the unit's address is %d.%d.%d.%d\n",
                own_ip[0], own_ip[1], own_ip[2], own_ip[3]);
    }
    close(fd);
}

static void start_link(void)
{
    static const int ports[] = { 50000, 50001, 50002 };
    pthread_t t;
    int i;

    if (link_started) {
        return;
    }
    link_started = 1;
    find_own_ip();
    for (i = 0; i < 3; i++) {
        pthread_create(&t, 0, link_listener, (void *)(long)ports[i]);
    }
}

int socket(int domain, int type, int proto)
{
    int (*real)(int, int, int) = dlsym(RTLD_NEXT, "socket");
    int sv[2], i;

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
    for (i = 0; i < PACKET_FDS; i++) {
        if (!packet_fd[i]) {
            packet_cooked[i] = type == SOCK_DGRAM;
            packet_fd[i] = sv[1];
            break;
        }
    }
    start_link();
    return sv[0];
}

/* The app opens display ":0.0" whatever DISPLAY says, which is the socket
 * /tmp/.X11-unix/X0. With DJSDEV_XDISPLAY=<n> that connection goes to display
 * n's abstract socket instead: an Xvfb started for the app, which under WSLg
 * cannot make a socket file (the folder is read-only there). */
int connect(int fd, const void *addr, unsigned len)
{
    int (*real)(int, const void *, unsigned) = dlsym(RTLD_NEXT, "connect");
    const unsigned char *a = addr;
    const char *n = getenv("DJSDEV_XDISPLAY");
    static const char X0[] = "/tmp/.X11-unix/X0";
    unsigned char to[64];
    unsigned at = 3, i;

    if (!n || !*n || !a || len < 2 + sizeof(X0) - 1 || a[0] != AF_UNIX || a[1] != 0) {
        return real(fd, addr, len);
    }
    i = a[2] ? 2 : 3;                   /* a path, or an abstract name */
    if (len < i + sizeof(X0) - 1 || memcmp(a + i, X0, sizeof(X0) - 1) ||
        (len > i + sizeof(X0) - 1 && a[i + sizeof(X0) - 1])) {
        return real(fd, addr, len);
    }
    memset(to, 0, sizeof(to));
    to[0] = AF_UNIX;
    memcpy(to + at, X0, sizeof(X0) - 2);            /* "@/tmp/.X11-unix/X" */
    at += sizeof(X0) - 2;
    while (*n && at < sizeof(to) - 1) {
        to[at++] = *n++;
    }
    fprintf(stderr, "[djsdev] connect(display :0) -> the display %s\n", getenv("DJSDEV_XDISPLAY"));
    return real(fd, to, at);
}

int bind(int fd, const void *addr, unsigned len)
{
    int (*real)(int, const void *, unsigned) = dlsym(RTLD_NEXT, "bind");
    const unsigned char *a = addr;
    int r;

    if (fake_fd(fd) == PACKET_NAME) {
        return 0;
    }
    r = real(fd, addr, len);
    if (r == 0 && fd >= 0 && fd < MAX_FD && a && len >= 8 && a[0] == AF_INET) {
        int port = a[2] << 8 | a[3];

        if (port >= 50000 && port <= 50002) {
            link_port[fd] = port;
            fprintf(stderr, "[djsdev] the app bound fd %d to UDP %d\n", fd, port);
        }
    }
    return r;
}

ssize_t recvfrom(int fd, void *buf, size_t n, int flags, void *addr, unsigned *alen)
{
    ssize_t (*real)(int, void *, size_t, int, void *, unsigned *) = dlsym(RTLD_NEXT, "recvfrom");
    ssize_t r = real(fd, buf, n, flags, addr, alen);

    if (r > 0x0a && fd >= 0 && fd < MAX_FD && link_port[fd] > 0) {
        int port = link_port[fd] - 50000, kind = ((unsigned char *)buf)[0x0a];
        int size = r > 0x200 ? 3 : r > 0x100 ? 2 : r > 0x40 ? 1 : 0;

        if (!link_seen[port][kind][size]) {
            link_seen[port][kind][size] = 1;
            fprintf(stderr, "[djsdev] the app received on UDP %d: type 0x%02x, %d bytes\n",
                    50000 + port, kind, (int)r);
        }
    }
    return r;
}

/* What the app sends on the Pro DJ Link ports, once for each kind. */
ssize_t sendto(int fd, const void *buf, size_t n, int flags, const void *addr, unsigned alen)
{
    ssize_t (*real)(int, const void *, size_t, int, const void *, unsigned) = dlsym(RTLD_NEXT, "sendto");

    if (addr && alen >= 8 && n > 0x0a && ((const unsigned char *)addr)[0] == AF_INET) {
        const unsigned char *a = addr;
        int port = a[2] << 8 | a[3], kind = ((const unsigned char *)buf)[0x0a];

        if (port >= 50000 && port <= 50002) {
            static unsigned char sent[3][256];

            if (!sent[port - 50000][kind]++) {
                fprintf(stderr, "[djsdev] the app sends to %d.%d.%d.%d:%d: type 0x%02x, %d bytes\n",
                        a[4], a[5], a[6], a[7], port, kind, (int)n);
            }
        }
    }
    return real(fd, buf, n, flags, addr, alen);
}

int setsockopt(int fd, int level, int name, const void *val, unsigned len)
{
    int (*real)(int, int, int, const void *, unsigned) = dlsym(RTLD_NEXT, "setsockopt");

    return fake_fd(fd) == PACKET_NAME ? 0 : real(fd, level, name, val, len);
}

/* The board's sound card is an AK4452 DAC, opened as "hw:ak4452audio,N"
 * (0: headphones and input, 1: master). It goes to the ALSA PCM named by
 * DJSDEV_PCM instead, "null" (discard, and silence on the inputs) by default.
 *
 * The app's ALSA code (its open routine) sizes its buffers from the channel
 * ranges the devices report. It asks for 4 outputs in all and gives each of
 * the two output devices as many as it accepts, so the board's must take
 * exactly 2 each (the AK4452 is a stereo DAC). With the 1-32 that "null"
 * reports the first device takes all 4, the second is given channels past
 * the end of the output buffer, and the audio thread crashes copying them
 * (in its audio thread); and if the input cannot be opened the
 * whole device fails to open, nothing gets a sample rate, and the startup
 * project load never finishes. So the ranges are narrowed to the board's. */
#define STAND_PCMS 16
static void *stand_pcm[STAND_PCMS];      /* handles opened in place of the AK4452 */
static int stand_stream[STAND_PCMS];
static void *ranged_params;              /* the hw_params last filled from one of them */
static int ranged_chans;
static void *master_pcm;                 /* the handles opened in place of hw:ak4452audio,1, */
static void *phones_pcm, *input_pcm;     /* of ,0 for playback and of ,0 for capture */

int snd_pcm_open(void **pcm, const char *name, int stream, int mode)
{
    int (*real)(void **, const char *, int, int) = dlsym(RTLD_NEXT, "snd_pcm_open");
    const char *to;
    int r, i;

    if (!name || !strstr(name, "ak4452audio")) {
        return real(pcm, name, stream, mode);
    }
    to = getenv("DJSDEV_PCM");
    if (!to || !*to) {
        to = "null";
    }
    r = real(pcm, to, stream, mode);
    fprintf(stderr, "[djsdev] snd_pcm_open(%s, %s) -> %s = %d\n", name, stream ? "capture" : "playback", to, r);
    if (r >= 0) {
        if (stream) {
            input_pcm = *pcm;
        } else if (strstr(name, ",1")) {
            master_pcm = *pcm;
        } else {
            phones_pcm = *pcm;
        }
        for (i = 0; i < STAND_PCMS; i++) {
            if (!stand_pcm[i] || stand_pcm[i] == *pcm) {
                stand_pcm[i] = *pcm;
                stand_stream[i] = stream;
                break;
            }
        }
    }
    return r;
}

/*
 * Playback. "null" takes what it is given at once, so the app's audio thread
 * (its audio thread: wait, write both outputs, read the input, run the callback)
 * would spin as fast as the CPU allows: time in the app would run fast and a
 * core would be burnt. The board's DAC takes 44100 frames a second, so the
 * write to the master output waits for that. What is written there is also
 * kept for the virtual deck, which plays it.
 */
#define RATE 44100
static long long pace_us;               /* when the master output is due its next frame */
static unsigned pace_rem;
static unsigned long stat_frames;
static float stat_peak;
static long long stat_us;

/* (Divisions are by constants and 32 bits wide: there is no libgcc here.) */
static long long now_us(void)
{
    struct timespec ts;

    clock_gettime(1 /* CLOCK_MONOTONIC */, &ts);
    return ts.tv_sec * 1000000ll + (unsigned long)ts.tv_nsec / 1000;
}

/* frames of sound for output ch (0 master, 1 headphones): left and right are
 * `step` floats apart. The master's sets the pace. */
static void audio_put(int ch, const float *l, const float *r, unsigned step, unsigned long frames)
{
    long long now;
    unsigned long i, us = frames * 1000000ul;   /* a block is at most a few thousand frames */
    unsigned w = ring_w[ch];

    if (ch) {
        for (i = 0; i < frames; i++, l += step, r += step, w++) {
            ring[ch][(w % RING_FRAMES) * 2] = *l;
            ring[ch][(w % RING_FRAMES) * 2 + 1] = *r;
        }
        ring_w[ch] = w;
        return;
    }
    now = now_us();

    for (i = 0; i < frames; i++, l += step, r += step) {
        float a = *l < 0 ? -*l : *l, b = *r < 0 ? -*r : *r;

        ring[0][(w % RING_FRAMES) * 2] = *l;
        ring[0][(w % RING_FRAMES) * 2 + 1] = *r;
        w++;
        if (a > stat_peak) {
            stat_peak = a;
        }
        if (b > stat_peak) {
            stat_peak = b;
        }
    }
    ring_w[0] = w;

    /* Real time: sleep until this block is due; start over after a stall. */
    if (pace_us < now - 100000) {
        pace_us = now;
    }
    pace_us += us / RATE;
    pace_rem += us % RATE;
    if (pace_rem >= RATE) {
        pace_rem -= RATE;
        pace_us++;
    }
    if (pace_us > now) {
        usleep((unsigned)(pace_us - now));
    }

    stat_frames += frames;
    if (now - stat_us >= 10000000) {
        if (stat_us && (stat_peak > 0.0001f || getenv("DJSDEV_AUDIO_LOG"))) {
            fprintf(stderr, "[djsdev] audio: %lu frames in %u ms, peak %d/1000\n",
                    stat_frames, (unsigned)(now - stat_us) / 1000, (int)(stat_peak * 1000));
        }
        stat_us = now;
        stat_frames = 0;
        stat_peak = 0;
    }
}

/*
 * The sample format. The app tries nine formats in turn and takes
 * the first the device accepts: "null" accepts 32-bit float, the first, but
 * the unit's AK4452 settles on S24_LE (24 bits in the low three bytes of a
 * 32-bit word; /proc/asound on a unit, 2026-10-02). The board's devices here
 * accept only that, so that the app writes what it writes on the unit, and
 * what passes through a preloaded library (a mod) is in the unit's format.
 */
#define FORMAT_S24_LE 6

int snd_pcm_hw_params_set_format(void *pcm, void *params, int format)
{
    int (*real)(void *, void *, int) = dlsym(RTLD_NEXT, "snd_pcm_hw_params_set_format");
    int i;

    for (i = 0; i < STAND_PCMS; i++) {
        if (pcm && stand_pcm[i] == pcm && format != FORMAT_S24_LE) {
            return -22;     /* -EINVAL */
        }
    }
    return real(pcm, params, format);
}

/* S24_LE frames as floats, for the deck, a block at a time: left and right
 * are `step` words apart. */
static void audio_put_s24(int ch, const int *l, const int *r, unsigned step, unsigned long frames)
{
    static float f[2 * 1024];
    unsigned long i, n;

    while (frames) {
        n = frames < 1024 ? frames : 1024;
        for (i = 0; i < n; i++, l += step, r += step) {
            f[2 * i] = (float)(*l << 8 >> 8) * (1.0f / 8388608.0f);
            f[2 * i + 1] = (float)(*r << 8 >> 8) * (1.0f / 8388608.0f);
        }
        audio_put(ch, f, f + 1, 2, n);
        frames -= n;
    }
}

long snd_pcm_writei(void *pcm, const void *buf, unsigned long frames)
{
    long (*real)(void *, const void *, unsigned long) = dlsym(RTLD_NEXT, "snd_pcm_writei");

    if (pcm == master_pcm || pcm == phones_pcm) {
        audio_put_s24(pcm == phones_pcm, buf, (const int *)buf + 1, 2, frames);
    }
    return real(pcm, buf, frames);
}

/* The input. The app reads interleaved frames and takes each sample as 24
 * bits in a 32-bit word, whatever format was agreed. What the deck
 * has sent is handed over; silence when there is not enough, and the oldest
 * is dropped when the deck's clock runs ahead of the app's. */
long snd_pcm_readi(void *pcm, void *buf, unsigned long frames)
{
    long (*real)(void *, void *, unsigned long) = dlsym(RTLD_NEXT, "snd_pcm_readi");
    int *out = buf;
    unsigned long i;
    unsigned r = in_r, have = in_w - r;

    if (pcm != input_pcm) {
        return real(pcm, buf, frames);
    }
    if (have > RING_FRAMES / 4) {           /* over 90 ms waiting: catch up */
        r = in_w - RING_FRAMES / 16;
        have = in_w - r;
    }
    for (i = 0; i < frames; i++) {
        if (have >= frames) {
            out[2 * i] = in_ring[(r % RING_FRAMES) * 2] << 8;
            out[2 * i + 1] = in_ring[(r % RING_FRAMES) * 2 + 1] << 8;
            r++;
        } else {
            out[2 * i] = out[2 * i + 1] = 0;
        }
    }
    in_r = r;
    return frames;
}

long snd_pcm_writen(void *pcm, void **bufs, unsigned long frames)
{
    long (*real)(void *, void **, unsigned long) = dlsym(RTLD_NEXT, "snd_pcm_writen");

    if (pcm == master_pcm || pcm == phones_pcm) {
        audio_put_s24(pcm == phones_pcm, bufs[0], bufs[1], 1, frames);
    }
    return real(pcm, bufs, frames);
}

int snd_pcm_close(void *pcm)
{
    int (*real)(void *) = dlsym(RTLD_NEXT, "snd_pcm_close");
    int i;

    for (i = 0; i < STAND_PCMS; i++) {
        if (stand_pcm[i] == pcm) {
            stand_pcm[i] = 0;
        }
    }
    if (pcm == master_pcm) {
        master_pcm = 0;
    }
    if (pcm == phones_pcm) {
        phones_pcm = 0;
    }
    if (pcm == input_pcm) {
        input_pcm = 0;
    }
    return real(pcm);
}

int snd_pcm_hw_params_any(void *pcm, void *params)
{
    int (*real)(void *, void *) = dlsym(RTLD_NEXT, "snd_pcm_hw_params_any");
    int i;

    if (ranged_params == params) {
        ranged_params = 0;
    }
    for (i = 0; i < STAND_PCMS; i++) {
        if (pcm && stand_pcm[i] == pcm) {
            ranged_params = params;
            ranged_chans = 2;   /* stereo in, stereo out */
        }
    }
    return real(pcm, params);
}

int snd_pcm_hw_params_get_channels_min(const void *params, unsigned *val)
{
    int (*real)(const void *, unsigned *) = dlsym(RTLD_NEXT, "snd_pcm_hw_params_get_channels_min");

    if (params != ranged_params) {
        return real(params, val);
    }
    *val = ranged_chans;
    return 0;
}

int snd_pcm_hw_params_get_channels_max(const void *params, unsigned *val)
{
    int (*real)(const void *, unsigned *) = dlsym(RTLD_NEXT, "snd_pcm_hw_params_get_channels_max");

    if (params != ranged_params) {
        return real(params, val);
    }
    *val = ranged_chans;
    return 0;
}

/* Unmounting needs privileges the app does not have here; the drive is a
 * folder anyway. */
int umount2(const char *path, int flags)
{
    int (*real)(const char *, int) = dlsym(RTLD_NEXT, "umount2");

    if (path && !strncmp(path, "/media/", 7)) {
        fprintf(stderr, "[djsdev] umount(%s) = 0\n", path);
        return 0;
    }
    return real(path, flags);
}

int umount(const char *path)
{
    return umount2(path, 0);
}

int close(int fd)
{
    int (*real)(int) = dlsym(RTLD_NEXT, "close");

    if (fake_fd(fd)) {
        fprintf(stderr, "[djsdev] close(%s)\n", fake_name[fd]);
        if (fake_spi[fd]) {
            fake_spi[fd]->on = 0;
        }
        int q;

        for (q = 0; q < QUEUES; q++) {
            if (fd == queue_fd[q]) {
                queue_fd[q] = -1;
            }
        }
        fake_name[fd] = 0;
        fake_spi[fd] = 0;
        {
            int p;

            for (p = 0; p < PACKET_FDS; p++) {
                if (fake_peer[fd] > 0 && packet_fd[p] == fake_peer[fd]) {
                    packet_fd[p] = 0;
                }
            }
        }
        if (fake_peer[fd] >= 0) {
            real(fake_peer[fd]);
        }
    }
    return real(fd);
}
