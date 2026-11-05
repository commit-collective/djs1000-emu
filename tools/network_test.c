/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Firmware-free Linux checks. Only loopback UDP is sent. */
#include <assert.h>
#include <dlfcn.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <net/if.h>
#include <arpa/inet.h>
#include "../shim/network.h"

static int untouched_ioctl(int fd, unsigned long request, void *arg)
{
    (void)fd; (void)request;
    assert(arg == (void *)1);
    return 123;
}

int main(void)
{
    int receiver = socket(AF_INET, SOCK_DGRAM, 0), sender = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in addr = { .sin_family = AF_INET }, from;
    struct timeval timeout = { .tv_sec = 2 };
    socklen_t length = sizeof(addr);
    struct ifreq request = {0};
    char data[8], index[16];
    unsigned char ip[4];
    int (*real_ioctl)(int, unsigned long, void *) = (void *)ioctl;
    assert(receiver >= 0 && sender >= 0);
    setenv("DJSDEV_INTERFACE", "lo", 1);
    setenv("DJSDEV_ADDRESS", "127.0.0.2", 1);
    setenv("DJSDEV_NETMASK", "255.0.0.0", 1);
    setenv("DJSDEV_BROADCAST", "127.255.255.255", 1);
    snprintf(index, sizeof(index), "%u", if_nametoindex("lo"));
    setenv("DJSDEV_IFINDEX", index, 1);
    assert(network_ioctl(sender, 0x1234, (void *)1, untouched_ioctl) == 123);
    assert(network_ioctl(sender, SIOCSIFADDR, (void *)1, untouched_ioctl) == 123);
    assert(network_ip("DJSDEV_ADDRESS", ip) && ip[3] == 2);
    assert(network_accept((unsigned char[]){127, 0, 0, 9}));
    assert(!network_accept((unsigned char[]){192, 168, 1, 1}));
    strcpy(request.ifr_name, "eth0");
    assert(network_ioctl(sender, SIOCGIFADDR, &request, real_ioctl) == 0);
    assert(!strcmp(request.ifr_name, "eth0"));
    assert(!memcmp((char *)&request + 20, ip, 4));
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    assert(!bind(receiver, (void *)&addr, sizeof(addr)));
    assert(!getsockname(receiver, (void *)&addr, &length));
    setsockopt(receiver, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    assert(network_send(sender, "test", 4, 0, &addr, sizeof(addr), (void *)sendmsg) == 4);
    assert(recvfrom(receiver, data, sizeof(data), 0, (void *)&from, &length) == 4);
    assert(!memcmp(data, "test", 4));
    assert(from.sin_addr.s_addr == inet_addr("127.0.0.2"));
    setenv("DJSDEV_INTERFACE", "", 1);
    assert(!network_selected());
    assert(network_accept((unsigned char[]){192, 168, 1, 1}));
    close(receiver); close(sender);
    puts("Network identity and loopback source routing passed");
    return 0;
}
