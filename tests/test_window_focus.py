import unittest
from unittest.mock import Mock,patch
import window_focus

class WindowFocusTests(unittest.TestCase):
    def test_restore_and_activate(self):
        api=object.__new__(window_focus.Windows);api.user=Mock()
        api.user.IsIconic.return_value=True;api.user.SetForegroundWindow.return_value=True
        api.activate(123)
        api.user.ShowWindowAsync.assert_called_once_with(123,9)
        api.user.SetForegroundWindow.assert_called_once_with(123)
        api.user.FlashWindow.assert_not_called()
    def test_denied_focus_flashes_without_resizing(self):
        api=object.__new__(window_focus.Windows);api.user=Mock()
        api.user.IsIconic.return_value=False;api.user.SetForegroundWindow.return_value=False
        api.activate(123)
        api.user.ShowWindowAsync.assert_not_called()
        api.user.FlashWindow.assert_called_once_with(123,True)
    def test_waits_for_window_then_stops(self):
        with patch.object(window_focus,'Windows') as windows,patch.object(window_focus,'_request',4),patch('window_focus.time.sleep'):
            windows.return_value.find.side_effect=[None,123]
            window_focus._focus('notepad',4)
            windows.return_value.activate.assert_called_once_with(123)
    def test_superseded_request_does_not_steal_focus(self):
        with patch.object(window_focus,'Windows') as windows,patch.object(window_focus,'_request',5):
            window_focus._focus('notepad',4)
            windows.return_value.find.assert_not_called()
