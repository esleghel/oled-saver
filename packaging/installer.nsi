; NSIS Installer Script for OLED Saver
; Requires NSIS 3.x

!include "MUI2.nsh"

Name "OLED Saver"
OutFile "oled-saver-windows-installer.exe"
InstallDir "$PROGRAMFILES\OLED Saver"
InstallDirRegKey HKLM "Software\OLEDSaver" "InstallDir"
RequestExecutionLevel admin

; UI
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"
!define MUI_ABORTWARNING

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Install"
    SetOutPath "$INSTDIR"

    ; Copy files
    File "..\dist\oled-saver.exe"
    File "..\LICENSE"
    File "..\README.md"

    ; Create uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Start Menu shortcut
    CreateDirectory "$SMPROGRAMS\OLED Saver"
    CreateShortcut "$SMPROGRAMS\OLED Saver\OLED Saver.lnk" "$INSTDIR\oled-saver.exe"
    CreateShortcut "$SMPROGRAMS\OLED Saver\Uninstall.lnk" "$INSTDIR\uninstall.exe"

    ; Autostart (current user)
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "OLEDSaver" "$INSTDIR\oled-saver.exe"

    ; Registry for uninstall
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OLEDSaver" "DisplayName" "OLED Saver"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OLEDSaver" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OLEDSaver" "InstallLocation" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OLEDSaver" "Publisher" "esleghel"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OLEDSaver" "DisplayVersion" "1.0.0"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OLEDSaver" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OLEDSaver" "NoRepair" 1

    ; Save install dir
    WriteRegStr HKLM "Software\OLEDSaver" "InstallDir" "$INSTDIR"
SectionEnd

Section "Uninstall"
    ; Remove autostart
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "OLEDSaver"

    ; Remove files
    Delete "$INSTDIR\oled-saver.exe"
    Delete "$INSTDIR\LICENSE"
    Delete "$INSTDIR\README.md"
    Delete "$INSTDIR\uninstall.exe"

    ; Remove shortcuts
    Delete "$SMPROGRAMS\OLED Saver\OLED Saver.lnk"
    Delete "$SMPROGRAMS\OLED Saver\Uninstall.lnk"
    RMDir "$SMPROGRAMS\OLED Saver"

    ; Remove install dir
    RMDir "$INSTDIR"

    ; Remove registry
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\OLEDSaver"
    DeleteRegKey HKLM "Software\OLEDSaver"
SectionEnd
