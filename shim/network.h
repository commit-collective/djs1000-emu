/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Explicit Linux adapter identity and per-datagram routing. No OS setters. */
static int network_selected(void)
{
    const char *name = getenv("DJSDEV_INTERFACE");
    return name && *name;
}

static int network_ip(const char *key, unsigned char out[4])
{
    const char *value = getenv(key);
    unsigned a, b, c, d;
    char tail;
    if (!value || sscanf(value, "%u.%u.%u.%u%c", &a, &b, &c, &d, &tail) != 4 ||
        a > 255 || b > 255 || c > 255 || d > 255) return 0;
    out[0] = a; out[1] = b; out[2] = c; out[3] = d;
    return 1;
}

static int network_ioctl(int fd, unsigned long req, void *arg,
                         int (*real)(int, unsigned long, void *))
{
    const char *name = getenv("DJSDEV_INTERFACE"), *key = 0;
    char saved[16];
    unsigned char ip[4];
    int result;
    switch (req) {
    case 0x8915: key = "DJSDEV_ADDRESS"; break;
    case 0x8919: key = "DJSDEV_BROADCAST"; break;
    case 0x891b: key = "DJSDEV_NETMASK"; break;
    case 0x8913: case 0x8921: case 0x8927: case 0x8933: break;
    default: return real(fd, req, arg);
    }
    if (!name || !*name || strlen(name) > 15 || !arg || memcmp(arg, "eth0", 5))
        return real(fd, req, arg);
    memcpy(saved, arg, 16);
    memset(arg, 0, 16);
    memcpy(arg, name, strlen(name));
    result = real(fd, req, arg);
    memcpy(arg, saved, 16);
    if (!result && key && network_ip(key, ip)) memcpy((char *)arg + 20, ip, 4);
    return result;
}

static int network_accept(const unsigned char ip[4])
{
    unsigned char own[4], mask[4];
    int i;
    if (!network_selected() || !network_ip("DJSDEV_ADDRESS", own) || !network_ip("DJSDEV_NETMASK", mask)) return 1;
    for (i = 0; i < 4; i++) if ((ip[i] & mask[i]) != (own[i] & mask[i])) return 0;
    return 1;
}

/* Linux ABI, using the target's size_t and pointer width. */
struct network_iovec { void *base; size_t length; };
struct network_message {
    void *address; unsigned address_length;
    struct network_iovec *vectors; size_t vector_count;
    void *control; size_t control_length; int flags;
};
struct network_control {
    size_t length; int level, type;
    int index; unsigned char source[4], address[4];
};

static ssize_t network_send(int fd, const void *buf, size_t n, int flags,
                            const void *addr, unsigned alen,
                            ssize_t (*real)(int, const struct network_message *, int))
{
    struct network_iovec vector = { (void *)buf, n };
    struct network_control control;
    struct network_message message;
    unsigned char destination[16], broadcast[4];
    const char *index = getenv("DJSDEV_IFINDEX");
    memset(&control, 0, sizeof(control));
    control.length = sizeof(size_t) + 2 * sizeof(int) + 3 * sizeof(int);
    control.level = 0; control.type = 8; /* IPPROTO_IP, IP_PKTINFO */
    control.index = index ? atoi(index) : 0;
    network_ip("DJSDEV_ADDRESS", control.source);
    memcpy(destination, addr, 16);
    if (!memcmp(destination + 4, "\xff\xff\xff\xff", 4) &&
        network_ip("DJSDEV_BROADCAST", broadcast)) memcpy(destination + 4, broadcast, 4);
    memset(&message, 0, sizeof(message));
    message.address = destination; message.address_length = 16;
    message.vectors = &vector; message.vector_count = 1;
    message.control = &control; message.control_length = sizeof(control);
    (void)alen;
    return real(fd, &message, flags);
}
