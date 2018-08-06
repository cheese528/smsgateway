#!/usr/bin/env python
# Module     : smsgateway.py
# Synopsis   : SMS Gateway with Windows System tray icon.
# Programmer : Chee Hoong Low - cheehoong@ubiquitoustech.org
# Date       : 11 Oct 2017
# Notes      : Based on (i.e. ripped off from) Simon Brunning and Mark Hammond's
#              win32gui_taskbar.py and win32gui_menu.py demos from PyWin32
'''TODO

For now, the demo at the bottom shows how to use it...'''
         
import os
import sys
import time
import multiprocessing
import logging
import win32api
import win32con
import win32gui_struct
try:
    import winxpgui as win32gui
except ImportError:
    import win32gui
from pywin.mfc import dialog
import struct
import sgserver, sgdatabase

class SysTrayIcon(object):
    '''TODO'''
    QUIT = 'QUIT'
    SPECIAL_ACTIONS = [QUIT]
    
    FIRST_ID = 1023
    
    log = logging.getLogger('smsgateway.SysTrayIcon')
    log.setLevel(sgserver.logLevel)

    def __init__(self,
                 icon,
                 text,
                 options,
                 on_quit=None,
                 default_menu_index=None,
                 window_class_name=None,):
        
        self.icon = icon
        self.hover_text = text
        self.on_quit = on_quit
        
        options = options + (('Quit', get_icon('door-open-out'), self.QUIT, None),)
        self._next_action_id = self.FIRST_ID
        self.menu_actions_by_id = set()
        self.menu_options = self._add_ids_to_menu_options(list(options))
        self.menu_actions_by_id = dict(self.menu_actions_by_id)
        del self._next_action_id
        
        
        self.default_menu_index = (default_menu_index or 0)
        self.window_class_name = window_class_name or "SMS Gateway"
        
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
        window_class.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW
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
            option_text, option_icon, option_action, option_checked = menu_option
            if callable(option_action) or option_action in self.SPECIAL_ACTIONS:
                self.menu_actions_by_id.add((self._next_action_id, (option_action, option_checked, None)))
                result.append(menu_option + (self._next_action_id,))
            elif non_string_iterable(option_action):
                result.append((option_text,
                               option_icon,
                               self._add_ids_to_menu_options(option_action),
                               option_checked,
                               self._next_action_id))
            else:
                self.log.warn('Unknown item {} {} {}'.format(option_text, option_icon, option_action))
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
            self.log.warn("Can't find icon file - using default.")
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
        for option_text, option_icon, option_action, option_checked, option_id in menu_options[::-1]:
            menuiteminfo = dict(text=option_text,wID=option_id)
            menu_checked = self.menu_actions_by_id[option_id][1]
            if menu_checked is not None:
                checkable_menu = menu
                if menu_checked:
                    menuiteminfo.update(dict(fState=win32con.MFS_CHECKED))
            else:
                checkable_menu = None
            self.menu_actions_by_id[option_id] = (self.menu_actions_by_id[option_id][0], 
                                                    menu_checked, 
                                                    checkable_menu)
            if option_icon:
                option_icon = self.prep_menu_icon(option_icon)
                self.menu_item_map[index] = (option_icon, None)
                menuiteminfo.update(dict(hbmpItem=win32con.HBMMENU_CALLBACK,dwItemData=index))
            if option_id not in self.menu_actions_by_id:     
                submenu = win32gui.CreatePopupMenu()
                self.create_menu(submenu, option_action)
                menuiteminfo.update(dict(hSubMenu=submenu))
            item, extras = win32gui_struct.PackMENUITEMINFO(**menuiteminfo)
            if option_icon: index += 1
            self.log.debug('id={} menu={} {}'.format(option_id,menu,self.menu_actions_by_id[option_id]))
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
        self.log.debug('id={} {}'.format(id, self.menu_actions_by_id[id]))
        menu_action, menu_checked, menu = self.menu_actions_by_id[id]   
        if menu_action == self.QUIT:
            win32gui.DestroyWindow(self.hwnd)
        else:
            if menu_checked is not None:
                # Our 'checkbox' items ('radio' items not handled for now)
                fState = win32gui.GetMenuState(menu, id, win32con.MF_BYCOMMAND)
                if fState & win32con.MF_CHECKED:
                    menu_checked = False
                    check_flags = win32con.MFS_UNCHECKED
                else:
                    menu_checked = True
                    check_flags = win32con.MFS_CHECKED
                self.menu_actions_by_id[id] = menu_action, menu_checked, None
                self.log.debug('Set Checkable Menu id={} fstate={} check_flags={}'.format(id, fState, check_flags))
                win32gui.CheckMenuItem(menu, id, check_flags)
                menu_action(self, menu_checked)
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

def get_icon(filename):
    return ((sys._MEIPASS + '/') if getattr(sys, 'frozen', False) else '') + 'assets/' + filename + '.ico'

server_running = False

def toggle_server(sysTrayIcon):
    global server_running
    if (not server_running):
        sgserver.start_server(sg_settings, db_server)
        server_running = True
        sysTrayIcon.icon = get_icon('mobile_phone')
        sysTrayIcon.refresh_icon()
    else:
        sgserver.signal_exit()
        server_running = False
        sysTrayIcon.icon = get_icon('mobile-phone-off')
        sysTrayIcon.refresh_icon()
        sysTrayIcon.log.debug('Waiting 10 secs for web and modem server to shutdown')
        time.sleep(10) # wait 10 secs

def server_port(sysTrayIcon):
    current_val = sg_settings.get('web_port')
    new_val = dialog.GetSimpleInput('Port', current_val, 'Web API Server Port')
    if new_val is not None: 
        sg_settings.save('web_port', new_val)

def modem_port(sysTrayIcon):
    current_val = sg_settings.get('com_port')
    new_val = dialog.GetSimpleInput('Port, i.e. COM3', current_val, 'GSM Modem Port')
    if new_val is not None: 
        sg_settings.save('com_port', new_val)

def min_send_interval(sysTrayIcon):
    current_val = sg_settings.get('min_send_interval')
    new_val = dialog.GetSimpleInput('Min time between SMS in secs', current_val, 'SMS Send Rate Limiting')
    if new_val is not None: 
        sg_settings.save('min_send_interval', new_val)

def set_key(sysTrayIcon):
    current_val = sg_settings.get('key')
    new_val = dialog.GetSimpleInput('Key', current_val, 'Secret Key')
    if new_val is not None: 
        sg_settings.save('key', new_val)

def autostart(sysTrayIcon, is_checked):
    sg_settings.save('autostart', is_checked)

def keyprotection(sysTrayIcon, is_checked):
    sg_settings.save('keyprotection', is_checked)

# Module multiprocessing is organized differently in Python 3.4+
# try:
    # # Python 3.4+
    # if sys.platform.startswith('win'):
        # import multiprocessing.popen_spawn_win32 as forking
    # else:
        # import multiprocessing.popen_fork as forking
# except ImportError:
    # import multiprocessing.forking as forking

# if sys.platform.startswith('win'):
    # # First define a modified version of Popen.
    # class _Popen(forking.Popen):
        # def __init__(self, *args, **kw):
            # if hasattr(sys, 'frozen'):
                # # We have to set original _MEIPASS2 value from sys._MEIPASS
                # # to get --onefile mode working.
                # os.putenv('_MEIPASS2', sys._MEIPASS)
            # try:
                # super(_Popen, self).__init__(*args, **kw)
            # finally:
                # if hasattr(sys, 'frozen'):
                    # # On some platforms (e.g. AIX) 'os.unsetenv()' is not
                    # # available. In those cases we cannot delete the variable
                    # # but only set it to the empty string. The bootloader
                    # # can handle this case.
                    # if hasattr(os, 'unsetenv'):
                        # os.unsetenv('_MEIPASS2')
                    # else:
                        # os.putenv('_MEIPASS2', '')

    # # Second override 'Popen' class with our modified version.
    # forking.Popen = _Popen

# Minimal self test. You'll need a bunch of ICO files in the current working
# directory in order for this to work...
if __name__ == '__main__':
    import itertools, glob
    
    multiprocessing.freeze_support()

    hover_text = "SMS Gateway Server"
    def bye(sysTrayIcon):
        global server_running, db_server
        if (server_running):
            sgserver.signal_exit()
        db_server.stop_thread()
        print 'Bye, then.'
    
    # Startup Database Server and get settings
    global db_server, sg_settings
    db_server, sg_settings = sgserver.init(sys.argv[1::])

    menu_options = (('SMS Gateway Server', get_icon('balloon_left'), toggle_server, None),
                    ('Set Server Port', get_icon('network-cloud'), server_port, None),
                    ('Set Modem Port', get_icon('plug-connect'), modem_port, None),
                    ('Set Send Interval', get_icon('time-remain'), min_send_interval, None),
                    ('Set Secret Key', get_icon('key'), set_key, None),
                    ('Require Secret Key', get_icon('lock'), keyprotection, int(sg_settings.get('keyprotection'))),
                    ('Autostart', get_icon('lightning-arrow'), autostart, int(sg_settings.get('autostart'))),
                    )

    if int(sg_settings.get('autostart')):
        sgserver.start_server(sg_settings, db_server)
        server_running = True
        runningicon = get_icon('mobile_phone')
    else:
        runningicon = get_icon('mobile-phone-off')

    SysTrayIcon(runningicon, hover_text, menu_options, on_quit=bye, default_menu_index=1)

    if server_running:
        logging.getLogger('smsgateway').debug('Waiting 10 secs for everything to shutdown')
        time.sleep(10) # wait 10 secs
