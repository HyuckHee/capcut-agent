"""CapCut 국제판용 자동 내보내기 — pycapcut 컨트롤러의 중국판 창 이름 하드코딩을 보정."""
import uiautomation as uia

from pycapcut.jianying_controller import ControlFinder, JianyingController
from pycapcut.exceptions import AutomationError

WINDOW_NAMES = ("CapCut", "CapCut专业版")
EXPORT_WINDOW_NAMES = ("내보내기", "Export", "导出")


class CapCutController(JianyingController):
    """창 이름 매칭만 로케일 무관하게 교체한 컨트롤러."""

    def get_window(self) -> None:
        if hasattr(self, "app") and self.app.Exists(0):
            self.app.SetTopmost(False)

        self.app = uia.WindowControl(searchDepth=1, Compare=self.__window_cmp)
        if not self.app.Exists(0):
            raise AutomationError("CapCut 창을 찾을 수 없습니다. CapCut을 실행한 뒤 다시 시도하세요.")

        # 내보내기 설정/진행 창이 떠 있으면 그쪽으로 전환
        for name in EXPORT_WINDOW_NAMES:
            export_window = self.app.WindowControl(searchDepth=1, Name=name)
            if export_window.Exists(0):
                self.app = export_window
                self.app_status = "pre_export"
                break

        self.app.SetActive()
        self.app.SetTopmost()

    def switch_to_home(self) -> None:
        if self.app_status == "home":
            return
        # 국제판은 홈/편집이 같은 MainWindow 클래스일 수 있어 화면 내용으로 홈 여부 판별
        probe = self.app.TextControl(
            searchDepth=2, Compare=ControlFinder.desc_matcher("HomePageDraftTitle"))
        if probe.Exists(2):
            self.app_status = "home"
            return
        try:
            super().switch_to_home()
        except Exception as e:
            raise AutomationError(
                "편집 화면에서 홈으로 자동 전환하지 못했습니다. "
                "CapCut에서 직접 홈(프로젝트 목록) 화면으로 나간 뒤 다시 실행해주세요."
            ) from e

    def __window_cmp(self, control: uia.WindowControl, depth: int) -> bool:
        if control.Name not in WINDOW_NAMES:
            return False
        class_name = control.ClassName.lower()
        if "homepage" in class_name:
            self.app_status = "home"
            return True
        if "mainwindow" in class_name:
            self.app_status = "edit"
            return True
        return False
