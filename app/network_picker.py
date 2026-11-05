# SPDX-License-Identifier: GPL-2.0-or-later
"""Restart-only network selection using interfaces visible to the Linux backend."""
import json
import subprocess


def query(command, *args):
    result = subprocess.run(command + list(args), capture_output=True, text=True, timeout=15,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'The backend could not read network setup')
    return json.loads(result.stdout)


def choose(command, surface=None):
    import pygame
    data = query(command, 'list')
    rows = [{'interface': '', 'address': ''}] + data['interfaces']
    own_window = surface is None
    if own_window:
        pygame.display.init()
        pygame.font.init()
        surface = pygame.display.set_mode((640, min(560, 220 + 36 * len(rows))), pygame.RESIZABLE)
        pygame.display.set_caption('DJS-1000 emulator · Network adapter')
    selected = next((i for i, row in enumerate(rows) if all(row.get(k) == data['selected'].get(k) for k in ('interface', 'address'))), 0)
    offset, message, clock = 0, '', pygame.time.Clock()
    font = pygame.font.SysFont('arial', 20, bold=True)
    small = pygame.font.SysFont('arial', 16)
    def text(value, x, y, colour=(225, 225, 225), face=font):
        surface.blit(face.render(value, True, colour), (x, y))
    try:
        while True:
            width, height = surface.get_size()
            visible = max(1, (height - 220) // 36)
            offset = max(0, min(offset, max(0, len(rows) - visible)))
            surface.fill((12, 12, 12))
            text('DJ network adapter', 20, 18)
            text('Choose an adapter available to the emulator backend.', 20, 53, face=small)
            text('Applies after restart. Save your project before restarting.', 20, 77, face=small)
            text('Host and VM network settings are unchanged.', 20, 101, face=small)
            rectangles = []
            for i in range(offset, min(len(rows), offset + visible)):
                row = rows[i]
                rect = pygame.Rect(16, 132 + (i - offset) * 36, width - 32, 34)
                pygame.draw.rect(surface, (45, 65, 40) if i == selected else (26, 26, 26), rect)
                title = '%s · %s/%s' % (row['interface'], row['address'], row['prefix']) if row['interface'] else 'Default / local testing (existing networking)'
                text(title, rect.x + 8, rect.y + 7, face=small)
                rectangles.append((rect, i))
            apply = pygame.Rect(width - 250, height - 50, 130, 34)
            cancel = pygame.Rect(width - 110, height - 50, 94, 34)
            pygame.draw.rect(surface, (45, 65, 40), apply)
            pygame.draw.rect(surface, (40, 40, 40), cancel)
            text('Save choice', apply.x + 8, apply.y + 7, face=small)
            text('Cancel', cancel.x + 14, cancel.y + 7, face=small)
            text(message or 'Use arrow keys or scroll to browse. Enter saves. Escape cancels.', 20, height - 82, face=small)
            pygame.display.flip()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if not own_window:
                        pygame.event.post(event)
                    return False
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return False
                if event.type == pygame.MOUSEWHEEL:
                    offset -= event.y
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_UP, pygame.K_DOWN):
                    selected = max(0, min(len(rows) - 1, selected + (1 if event.key == pygame.K_DOWN else -1)))
                    offset = min(selected, max(offset, selected - visible + 1))
                click = event.type == pygame.MOUSEBUTTONUP and event.button == 1
                if click:
                    for rect, i in rectangles:
                        if rect.collidepoint(event.pos):
                            selected = i
                    if cancel.collidepoint(event.pos):
                        return False
                if (click and apply.collidepoint(event.pos)) or (event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN):
                    try:
                        row = rows[selected]
                        query(command, 'select', row['interface'], row['address'])
                        return True
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        message = str(error)
            clock.tick(30)
    finally:
        if own_window:
            pygame.display.quit()
