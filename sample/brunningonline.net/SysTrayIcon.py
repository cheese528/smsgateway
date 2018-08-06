#!/usr/bin/env python
# Module     : SysTrayIcon.py
# Synopsis   : Windows System tray icon.
# Programmer : Simon Brunning - simon@brunningonline.net
# Date       : 11 April 2005
# Notes      : Based on (i.e. ripped off from) Mark Hammond's
#              win32gui_taskbar.py and win32gui_menu.py demos from PyWin32
'''TODO

For now, the demo at the bottom shows how to use it...'''
         
import os
import sys
import win32api
import win32con
import win32gui_struct
try:
    import winxpgui as win32gui
except ImportError:
    import win32gui
import struct

class SysTrayIcon(object):
    '''TODO'''
    QUIT = 'QUIT'
    SPECIAL_ACTIONS = [QUIT]
    
    FIRST_ID = 1023
    
    def __init__(self,
                 icon,
                 hover_text,
                 menu_options,
                 on_quit=None,
                 default_menu_index=None,
                 window_class_name=None,):
        
        self.icon = icon
        self.hover_text = hover_text
        self.on_quit = on_quit
        
        menu_options = menu_options + (('Quit', None, self.QUIT),)
        self._next_action_id = self.FIRST_ID
        self.menu_actions_by_id = set()
        self.menu_options = self._add_ids_to_menu_options(list(menu_options))
        self.menu_actions_by_id = dict(self.menu_actions_by_id)
        del self._next_action_id
        
        
        self.default_menu_index = (default_menu_index or 0)
        self.window_class_name = window_class_name or "SysTrayIconPy"
        
        message_map = {win32gui.RegisterWindowMessage("TaskbarCreated"): self.restart,
                       win32con.WM_DESTROY: self.destroy,
                       win32con.WM_COMMAND: self.command,
                       # owner-draw related handlers.
                       win32con.WM_MEASUREITEM: self.OnMeasureItem,
                       win32con.WM_DRAWITEM: self.OnDrawItem,
                       win32con.WM_USER+20 : self.notify,}
        # Register the Window class.
        window_class = win32gui.WNDCLASS()
        hinst = window_class.hInstance = win32gui.GetModuleHandle(None)
        window_class.lpszClassName = self.window_class_name
        window_class.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW;
        window_class.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        window_class.hbrBackground = win32con.COLOR_WINDOW
        window_class.lpfnWndProc = message_map # could also specify a wndproc.
        classAtom = win32gui.RegisterClass(window_class)
        # Create the Window.
        style = win32con.WS_OVERLAPPED | win32con.WS_SYSMENU
        self.hwnd = win32gui.CreateWindow(classAtom,
                                          self.window_class_name,
                                          style,
                                          0,
                                          0,
                                          win32con.CW_USEDEFAULT,
                                          win32con.CW_USEDEFAULT,
                                          0,
                                          0,
                                          hinst,
                                          None)
        win32gui.UpdateWindow(self.hwnd)
        self.notify_id = None
        self.refresh_icon()
        
        # Load up some information about menus needed by our owner-draw code.
        # The font to use on the menu.
        ncm = win32gui.SystemParametersInfo(win32con.SPI_GETNONCLIENTMETRICS)
        self.font_menu = win32gui.CreateFontIndirect(ncm['lfMenuFont'])
        # spacing for our ownerdraw menus - not sure exactly what constants
        # should be used (and if you owner-draw all items on the menu, it
        # doesn't matter!)
        self.menu_icon_height = win32api.GetSystemMetrics(win32con.SM_CYMENU) - 4
        self.menu_icon_width = self.menu_icon_height
        self.icon_x_pad = 8 # space from end of icon to start of text.
        # A map we use to stash away data we need for ownerdraw.  Keyed
        # by integer ID - that ID will be set in dwTypeData of the menu item.
        self.menu_item_map = {}
        
        win32gui.PumpMessages()

    def _add_ids_to_menu_options(self, menu_options):
        result = []
        for menu_option in menu_options:
            option_text, option_icon, option_action = menu_option
            if callable(option_action) or option_action in self.SPECIAL_ACTIONS:
                self.menu_actions_by_id.add((self._next_action_id, option_action))
                result.append(menu_option + (self._next_action_id,))
            elif non_string_iterable(option_action):
                result.append((option_text,
                               option_icon,
                               self._add_ids_to_menu_options(option_action),
                               self._next_action_id))
            else:
                print 'Unknown item', option_text, option_icon, option_action
            self._next_action_id += 1
        return result
        
    def refresh_icon(self):
        # Try and find a custom icon
        hinst = win32gui.GetModuleHandle(None)
        if os.path.isfile(self.icon):
            icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
            hicon = win32gui.LoadImage(hinst,
                                       self.icon,
                                       win32con.IMAGE_ICON,
                                       0,
                                       0,
                                       icon_flags)
        else:
            print "Can't find icon file - using default."
            hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        if self.notify_id: message = win32gui.NIM_MODIFY
        else: message = win32gui.NIM_ADD
        self.notify_id = (self.hwnd,
                          0,
                          win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                          win32con.WM_USER+20,
                          hicon,
                          self.hover_text)
        win32gui.Shell_NotifyIcon(message, self.notify_id)

    def restart(self, hwnd, msg, wparam, lparam):
        self.refresh_icon()

    def destroy(self, hwnd, msg, wparam, lparam):
        if self.on_quit: self.on_quit(self)
        nid = (self.hwnd, 0)
        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
        win32gui.PostQuitMessage(0) # Terminate the app.

    def notify(self, hwnd, msg, wparam, lparam):
        if lparam==win32con.WM_LBUTTONDBLCLK:
            self.execute_menu_option(self.default_menu_index + self.FIRST_ID)
        elif lparam==win32con.WM_RBUTTONUP:
            self.show_menu()
        elif lparam==win32con.WM_LBUTTONUP:
            pass
        return True
        
    def show_menu(self):
        menu = win32gui.CreatePopupMenu()
        self.create_menu(menu, self.menu_options)
        #win32gui.SetMenuDefaultItem(menu, 1000, 0)
        
        pos = win32gui.GetCursorPos()
        # See http://msdn.microsoft.com/library/default.asp?url=/library/en-us/winui/menus_0hdi.asp
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(menu,
                                win32con.TPM_LEFTALIGN,
                                pos[0],
                                pos[1],
                                0,
                                self.hwnd,
                                None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
    
    def create_menu(self, menu, menu_options):
        index = 0
        for option_text, option_icon, option_action, option_id in menu_options[::-1]:
            if option_icon:
                option_icon = self.prep_menu_icon(option_icon)
                self.menu_item_map[index] = (option_icon, option_text)
            if option_id in self.menu_actions_by_id:     
                if option_icon:           
                    item, extras = win32gui_struct.PackMENUITEMINFO(fType=win32con.MFT_OWNERDRAW,
                                                                    dwItemData=index,
                                                                    wID=option_id)
                else:
                    item, extras = win32gui_struct.PackMENUITEMINFO(text=option_text,
                                                                    wID=option_id)
            else:
                submenu = win32gui.CreatePopupMenu()
                self.create_menu(submenu, option_action)
                if option_icon:           
                    item, extras = win32gui_struct.PackMENUITEMINFO(fType=win32con.MFT_OWNERDRAW,
                                                                    dwItemData=index,
                                                                    wID=option_id,
                                                                    hSubMenu=submenu)
                else:
                    item, extras = win32gui_struct.PackMENUITEMINFO(text=option_text,
                                                                    wID=option_id,
                                                                    hSubMenu=submenu)
            index = index + 1
            win32gui.InsertMenuItem(menu, 0, 1, item)

    def prep_menu_icon(self, icon):
        # First load the icon.
        ico_x = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
        ico_y = win32api.GetSystemMetrics(win32con.SM_CYSMICON)
        hicon = win32gui.LoadImage(0, icon, win32con.IMAGE_ICON, ico_x, ico_y, win32con.LR_LOADFROMFILE)
        return hicon

    def command(self, hwnd, msg, wparam, lparam):
        id = win32gui.LOWORD(wparam)
        self.execute_menu_option(id)
        
    def execute_menu_option(self, id):
        menu_action = self.menu_actions_by_id[id]      
        if menu_action == self.QUIT:
            win32gui.DestroyWindow(self.hwnd)
        else:
            menu_action(self)
            
    # Owner-draw related functions.  We only have 1 owner-draw item, but
    # we pretend we have more than that :)
    def OnMeasureItem(self, hwnd, msg, wparam, lparam):
        fmt = "5iP"
        buf = win32gui.PyMakeBuffer(struct.calcsize(fmt), lparam)
        data = struct.unpack(fmt, buf)
        ctlType, ctlID, itemID, itemWidth, itemHeight, itemData = data

        hicon, text = self.menu_item_map[itemData]
        if text is None:
            # Only drawing icon due to HBMMENU_CALLBACK
            cx = self.menu_icon_width
            cy = self.menu_icon_height
        else:
            # drawing the lot!
            dc = win32gui.GetDC(hwnd)
            oldFont = win32gui.SelectObject(dc, self.font_menu)
            cx, cy = win32gui.GetTextExtentPoint32(dc, text)
            win32gui.SelectObject(dc, oldFont)
            win32gui. ReleaseDC(hwnd, dc)
    
            cx += win32api.GetSystemMetrics(win32con.SM_CXMENUCHECK)
            cx += self.menu_icon_width + self.icon_x_pad
    
            cy = win32api.GetSystemMetrics(win32con.SM_CYMENU)
            
        new_data = struct.pack(fmt, ctlType, ctlID, itemID, cx, cy, itemData)
        win32gui.PySetMemory(lparam, new_data)
        return True 

    def OnDrawItem(self, hwnd, msg, wparam, lparam):
        fmt = "5i2P4iP"
        data = struct.unpack(fmt, win32gui.PyGetString(lparam, struct.calcsize(fmt)))
        ctlType, ctlID, itemID, itemAction, itemState, hwndItem, \
                hDC, left, top, right, bot, itemData = data

        rect = left, top, right, bot
        hicon, text = self.menu_item_map[itemData]

        if text is None:
            # This means the menu-item had HBMMENU_CALLBACK - so all we
            # draw is the icon.  rect is the entire area we should use.
            win32gui.DrawIconEx(hDC, left, top, hicon, right-left, bot-top,
                       0, 0, win32con.DI_NORMAL)
        else:
            # If the user has selected the item, use the selected 
            # text and background colors to display the item.
            selected = itemState & win32con.ODS_SELECTED
            if selected:
                crText = win32gui.SetTextColor(hDC, win32gui.GetSysColor(win32con.COLOR_HIGHLIGHTTEXT))
                crBkgnd = win32gui.SetBkColor(hDC, win32gui.GetSysColor(win32con.COLOR_HIGHLIGHT))
    
            each_pad = self.icon_x_pad // 2
            x_icon = left + each_pad
            x_text = x_icon + self.menu_icon_width + each_pad
    
            # Draw text first, specifying a complete rect to fill - this sets
            # up the background (but overwrites anything else already there!)
            # Select the font, draw it, and restore the previous font.
            hfontOld = win32gui.SelectObject(hDC, self.font_menu)
            win32gui.ExtTextOut(hDC, x_text, top+2, win32con.ETO_OPAQUE, rect, text)
            win32gui.SelectObject(hDC, hfontOld)
    
            # Icon image next.  Icons are transparent - no need to handle
            # selection specially.
            win32gui.DrawIconEx(hDC, x_icon, top+2, hicon,
                       self.menu_icon_width, self.menu_icon_height,
                       0, 0, win32con.DI_NORMAL)
     
            # Return the text and background colors to their 
            # normal state (not selected). 
            if selected:
                win32gui.SetTextColor(hDC, crText)
                win32gui.SetBkColor(hDC, crBkgnd)

def non_string_iterable(obj):
    try:
        iter(obj)
    except TypeError:
        return False
    else:
        return not isinstance(obj, basestring)

# Minimal self test. You'll need a bunch of ICO files in the current working
# directory in order for this to work...
if __name__ == '__main__':
    import itertools, glob
    
    icons = itertools.cycle(glob.glob(((sys._MEIPASS + '/') if getattr(sys, 'frozen', False) else '') + '*.ico'))
    hover_text = "SysTrayIcon.py Demo"
    def hello(sysTrayIcon): print "Hello World."
    def simon(sysTrayIcon): print "Hello Simon."
    def switch_icon(sysTrayIcon):
        sysTrayIcon.icon = icons.next()
        sysTrayIcon.refresh_icon()
    menu_options = (('Say Hello', icons.next(), hello),
                    ('Switch Icon', None, switch_icon),
                    ('A sub-menu', icons.next(), (('Say Hello to Simon', icons.next(), simon),
                                                  ('Switch Icon', icons.next(), switch_icon),
                                                 ))
                   )
    def bye(sysTrayIcon): print 'Bye, then.'
    
    SysTrayIcon(icons.next(), hover_text, menu_options, on_quit=bye, default_menu_index=1)