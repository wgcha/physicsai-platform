# ==============================================================================
# HyperView 컨투어 스크린샷 & 애니메이션 동영상 저장 단독 실행 Tcl 스크립트
# ==============================================================================
# 출처: 사용자 제공 이슈 #2, HyperView 26.1 확인(GUI와 배치 hw -b -tcl 모두).
# PhysicsAI 플랫폼(phase3 §15 S10)이 바꾼 곳은 두 군데뿐이다(나머지 동작은 원본 그대로):
#   (a) 1절 "사용자 설정" 블록 → 같은 폴더의 capture_settings.tcl(작업마다 플랫폼이 생성)을 source
#   (b) 6·7절 저장 부분 → VIEWS 목록 반복(h3d는 한 번만 열고 방향마다 view orientation | view fit →
#       <view>.png → <view>.<VID_EXT>), 끝에 capture_result.txt(방향별 성공·파일 이름·오류)를 쓰고 exit.
#       배치에서 멈추지 않도록 2절 오류의 return도 capture_result.txt 작성 + exit로 바꿨다.
#   (c) S16(§21.4.2): 동영상 저장 범위 VID_SCOPE(page|window), 저장 성공 보고 뒤 파일 존재·크기 확인.

# ------------------------------------------------------------------------------
# 1. 설정 (경로 및 옵션) — 플랫폼이 만든 capture_settings.tcl
#    H3D_PATH OUTDIR FIELD DCOMP AVGMODE USE_LAST LEGMIN LEGMAX SAVE_VIDEO VID_EXT VID_SCOPE COMPS VIEWS
# ------------------------------------------------------------------------------
source [file join [file dirname [info script]] capture_settings.tcl]

# capture_result.txt 행: 방향마다 {view image_ok image_file video_state video_file error}
set CAPTURE_RESULTS [list]

proc capture_clean {s} {
    return [string map [list "|" "/" "\r" " " "\n" " "] $s]
}

proc capture_finish {status {msg ""}} {
    global OUTDIR CAPTURE_RESULTS
    catch {
        set fh [open [file join $OUTDIR capture_result.txt] w]
        fconfigure $fh -encoding utf-8
        puts $fh "# capture_result 1"
        puts $fh "STATUS=$status"
        if {$msg ne ""} { puts $fh "MESSAGE=[capture_clean $msg]" }
        foreach r $CAPTURE_RESULTS {
            set fields [list]
            foreach f $r { lappend fields [capture_clean $f] }
            puts $fh "VIEW=[join $fields |]"
        }
        close $fh
    }
    catch { exit }
}

# ------------------------------------------------------------------------------
# 2. 클라이언트 초기화 및 모델/결과 로드
# ------------------------------------------------------------------------------
proc relall {} {
    foreach h {hvSess hvProj hvPage hvWin hvPost hvModel hvResult hvContour hvLeg hvComp} {
        if {[info commands $h] ne ""} { catch {$h ReleaseHandle} ; catch {rename $h ""} }
    }
}

relall
catch { hwc delete client }

if {[catch { hwc open animation modelandresult "$H3D_PATH" "$H3D_PATH" } err]} {
    puts "ERROR: 파일 열기 실패 - $err"
    capture_finish OPEN_ERROR $err
    return
}

# HWI 핸들 획득
if {[catch {
    hwi GetSessionHandle hvSess
    hvSess GetProjectHandle hvProj
    hvProj GetPageHandle hvPage [hvProj GetActivePage]
    hvPage GetWindowHandle hvWin [hvPage GetActiveWindow]
    hvWin GetClientHandle hvPost
    hvPost GetModelHandle hvModel [hvPost GetActiveModel]
    hvModel GetResultCtrlHandle hvResult
} err]} {
    puts "ERROR: 핸들 획득 실패 - $err"
    capture_finish HANDLE_ERROR $err
    return
}

# ------------------------------------------------------------------------------
# 3. 서브케이스 및 프레임(Simulation) 확인 / 마지막 프레임 이동
# ------------------------------------------------------------------------------
set sub ""
catch { hvResult GetCurrentSubcase } sub
if {$sub eq "" || [string match *invalid* $sub]} {
    catch { hvResult GetSubcaseList } sl
    set sub [lindex $sl 0]
}
set nsim 0
catch { hvResult GetNumberOfSimulations $sub } nsim

if {$USE_LAST && [string is integer -strict $nsim] && $nsim > 0} {
    catch { hvResult SetCurrentSimulation [expr {$nsim - 1}] }
}

# ------------------------------------------------------------------------------
# 4. 컨투어(Result Scalar) 로드
# ------------------------------------------------------------------------------
if {$FIELD ne ""} {
    set cmd "result scalar load type= \"$FIELD\""
    if {$DCOMP ne ""} { append cmd " component= \"$DCOMP\"" }
    if {$AVGMODE ne ""} { append cmd " avgmode= $AVGMODE" }
    append cmd " displayed=true"
    if {[catch { hwc {*}$cmd } err]} {
        # 성분/avgmode 적용 실패 시 기본 type만 로드 재시도
        catch { hwc result scalar load type= "$FIELD" displayed=true }
    }
    catch { hwc result scalar legendmaxenabled false | result scalar legendminenabled false }
}

# ------------------------------------------------------------------------------
# 5. 부품 표시/격리 (COMPS가 지정된 경우)
# ------------------------------------------------------------------------------
if {[llength $COMPS] > 0} {
    catch { hwc hide component all }
    foreach comp $COMPS {
        catch { hwc show component "$comp" }
    }
    if {$USE_LAST && [string is integer -strict $nsim] && $nsim > 0} {
        catch { hvResult SetCurrentSimulation [expr {$nsim - 1}] }
    }
}

# 범례 수동 Min/Max 지정
if {$LEGMIN ne ""} { catch { hwc result scalar legendminenabled true | result scalar legendmin $LEGMIN } }
if {$LEGMAX ne ""} { catch { hwc result scalar legendmaxenabled true | result scalar legendmax $LEGMAX } }

# ------------------------------------------------------------------------------
# 6~7. 방향(VIEWS)마다: 카메라 뷰 정렬 및 화면 맞춤 → 스크린샷(<view>.png) → 동영상(<view>.<VID_EXT>)
#      파일 이름은 플랫폼이 고정 이름으로 찾는다.
# ------------------------------------------------------------------------------
set n_ok 0
foreach VIEW $VIEWS {
    # 앞 방향의 동영상 저장이 프레임을 옮겼을 수 있어 3절의 기준 프레임으로 되돌린다
    if {$USE_LAST && [string is integer -strict $nsim] && $nsim > 0} {
        catch { hvResult SetCurrentSimulation [expr {$nsim - 1}] }
    } else {
        catch { hvResult SetCurrentSimulation 0 }
    }
    catch { hwc view orientation $VIEW | view fit }

    set err_txt ""

    # (1) 이미지 스크린샷 저장 (.png)
    set png_ok 0
    set png_name "${VIEW}.png"
    set png_path [file join $OUTDIR $png_name]
    if {[catch { hwc save image window "$png_path" } err]} {
        puts "ERROR: 이미지 저장 실패 - $err"
        append err_txt "image: $err; "
    } else {
        puts "SUCCESS: 스크린샷 저장 완료 -> $png_path"
        set png_ok 1
        incr n_ok
    }

    # (2) 애니메이션 동영상 저장 (.mp4 / .avi / .gif)
    set vid_state "-"
    set vid_name ""
    if {$SAVE_VIDEO} {
        set vid_name "${VIEW}.${VID_EXT}"
        set vid_path [file join $OUTDIR $vid_name]
        # 저장 범위 VID_SCOPE(page|window, capture.video_scope — 설정 파일에 없으면 page = 원본 동작)
        if {[info exists VID_SCOPE] && $VID_SCOPE eq "window"} {
            set vid_cmd [list hwc save animation window $vid_path]
        } else {
            set vid_cmd [list hwc save animation page $vid_path]
        }
        if {[catch { {*}$vid_cmd } err]} {
            puts "ERROR: 동영상 저장 실패 - $err"
            append err_txt "video: $err; "
            set vid_state 0
        } elseif {![file exists $vid_path] || [file size $vid_path] <= 0} {
            # HyperView가 성공을 보고해도 파일이 없거나 0바이트일 수 있다(phase3 §21.4.2 S16)
            puts "ERROR: 동영상 파일 없음 - $vid_path"
            append err_txt "video: 파일이 만들어지지 않았습니다(HyperView 성공 보고); "
            set vid_state 0
        } else {
            puts "SUCCESS: 동영상 저장 완료 -> $vid_path"
            set vid_state 1
        }
    }
    lappend CAPTURE_RESULTS [list $VIEW $png_ok $png_name $vid_state $vid_name [string trim $err_txt]]
}

# 배치 실행 완료 후 결과 목록을 쓰고 HyperView 종료
capture_finish [expr {$n_ok > 0 ? "OK" : "SAVE_ERROR"}]
