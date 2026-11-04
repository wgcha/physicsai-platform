# ==============================================================================
# h3d 프레임 수·시각 경량 조회(배치) — ③-1 데이터 점검 DH_FRAMES (data-health.md DH-18, §3.6)
# ==============================================================================
# PhysicsAI 플랫폼이 DATA_HEALTH 작업(DH_FRAMES)에서 `hw -clientconfig hwpost.dat -b -tcl h3d_frame_probe.tcl`을 1회 실행한다.
# 대상 h3d가 여러 개여도 hw는 한 번만 띄운다(HyperWorks 유닛 1회) — 파일마다 열기 → 프레임 수·라벨 조회 → 닫기를 반복한다.
# contour_extract.tcl 2절(모델·결과 열기, relall, 핸들)과 GetNumberOfSimulations·GetSimulationLabel 부분만 재사용한다.
# 결과 스칼라·변위·요소·노드를 읽지 않는다(contour_extract.tcl 3절 이후는 쓰지 않음) — 이 파일은 프레임 수와 시각 라벨만 얻는다.
#
# 입력: 이 파일과 같은 폴더의 frame_probe_settings.tcl 하나뿐. 거기서 PROBE_TARGETS(= {idx h3d out} 목록)를 읽는다.
# 출력: 각 대상의 out 경로에만 쓴다(extract_result.txt 형식, UTF-8·LF — 플랫폼이 contour3d.settings 파서로 읽는다):
#   # h3d_frame_probe 1
#   STATUS=OK|OPEN_ERROR|PROBE_ERROR
#   MESSAGE=<오류 문구>                (실패일 때)
#   FRAMES_TOTAL=<프레임 수>          (GetNumberOfSimulations, 1 미만이면 1 — contour_extract와 같은 규칙)
#   FRAME=<번호>|<번호>|<시간>         (프레임마다: 0부터 번호, 시간 = GetSimulationLabel 문자열 — 숫자 추출은 플랫폼)
# 파일 하나의 열기 실패는 STATUS=OPEN_ERROR + MESSAGE를 쓰고 다음 파일로 계속한다.
# 단독 실행(frame_probe_settings.tcl 없음)은 안내를 출력하고 끝낸다 — 플랫폼 작업 폴더에서 실행한다.

# ------------------------------------------------------------------------------
# 1. 설정 — 플랫폼이 만든 frame_probe_settings.tcl: PROBE_TARGETS
# ------------------------------------------------------------------------------
set _cfg [file join [file dirname [info script]] frame_probe_settings.tcl]
if {![file exists $_cfg]} {
    puts "h3d_frame_probe: frame_probe_settings.tcl not found - run from the platform job folder."
    puts "h3d_frame_probe: frame_probe_settings.tcl 없음 - 플랫폼 작업 폴더에서 실행하세요."
    catch { exit }
    return
}
set PROBE_TARGETS [list]
source $_cfg

proc fp_clean {s} {
    return [string map [list "|" "/" "\r" " " "\n" " "] $s]
}

# out 경로에 결과 파일 1개를 쓴다. frames = {번호 라벨} 목록
proc fp_write {out status total frames {msg ""}} {
    catch {
        set fh [open $out w]
        fconfigure $fh -encoding utf-8 -translation lf
        puts $fh "# h3d_frame_probe 1"
        puts $fh "STATUS=$status"
        if {$msg ne ""} { puts $fh "MESSAGE=[fp_clean $msg]" }
        puts $fh "FRAMES_TOTAL=$total"
        foreach f $frames { puts $fh "FRAME=[lindex $f 0]|[lindex $f 0]|[fp_clean [lindex $f 1]]" }
        close $fh
    }
}

proc relall {} {
    foreach h {hvSess hvProj hvPage hvWin hvPost hvModel hvResult} {
        if {[info commands $h] ne ""} { catch {$h ReleaseHandle} ; catch {rename $h ""} }
    }
}

# ------------------------------------------------------------------------------
# 2. 파일마다 열기 → 프레임 수·라벨 → 닫기(contour_extract.tcl 2절과 같은 코드)
# ------------------------------------------------------------------------------
proc fp_probe {h3d out} {
    relall
    catch { hwc delete client }
    if {[catch { hwc open animation modelandresult "$h3d" "$h3d" } err]} {
        fp_write $out OPEN_ERROR 0 {} $err
        return
    }
    if {[catch {
        hwi GetSessionHandle hvSess
        hvSess GetProjectHandle hvProj
        hvProj GetPageHandle hvPage [hvProj GetActivePage]
        hvPage GetWindowHandle hvWin [hvPage GetActiveWindow]
        hvWin GetClientHandle hvPost
        hvPost GetModelHandle hvModel [hvPost GetActiveModel]
        hvModel GetResultCtrlHandle hvResult
    } err]} {
        fp_write $out OPEN_ERROR 0 {} $err
        return
    }
    set sub ""
    catch { hvResult GetCurrentSubcase } sub
    if {$sub eq "" || [string match *invalid* $sub]} {
        catch { hvResult GetSubcaseList } sl
        set sub [lindex $sl 0]
    }
    set nsim 0
    catch { hvResult GetNumberOfSimulations $sub } nsim
    if {![string is integer -strict $nsim] || $nsim < 1} { set nsim 1 }
    set frames [list]
    for {set k 0} {$k < $nsim} {incr k} {
        set t ""
        catch { hvResult GetSimulationLabel $sub $k } t
        lappend frames [list $k $t]
    }
    fp_write $out OK $nsim $frames
}

foreach tgt $PROBE_TARGETS {
    lassign $tgt idx h3d out
    if {[catch { fp_probe $h3d $out } err]} {
        fp_write $out PROBE_ERROR 0 {} $err
    }
    relall
    catch { hwc delete client }
}
catch { exit }
