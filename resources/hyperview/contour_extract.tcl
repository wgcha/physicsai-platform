# ==============================================================================
# HyperView 결과 3D 컨투어 추출(배치) — contour_capture.tcl의 형제 파일(geometry-view.md §13.3)
# ==============================================================================
# PhysicsAI 플랫폼이 CONTOUR_3D 작업(C3_EXTRACT)에서 `hw -clientconfig hwpost.dat -b -tcl contour_extract.tcl`로 실행한다.
# contour_capture.tcl의 동작은 바꾸지 않는다. h3d 열기·핸들·결과 종류/성분/평균 방식 절은 contour_capture.tcl과 같은 코드(복사 재사용).
# 출력 계약(OUTDIR, UTF-8, LF — 플랫폼이 이 파일들로 판정한다. hw 명령 이름은 현장 버전 확인 후 이 TCL에서만 바꾼다):
#   extract_result.txt  # contour_extract 1 / STATUS=OK|OPEN_ERROR|FIELD_ERROR|EXTRACT_ERROR / MESSAGE= / UNIT= / FIELD= DCOMP= AVGMODE=
#                       / NODES= FACES= FRAMES_TOTAL= / DISP= DISP_REASON= DISP_MISSING_FRAMES= SCOPE= / FRAME=<out_idx>|<src_idx>|<time>
#     NODES  = 사용 노드 수(요소가 쓰는 노드, 내부 노드 포함). 외부 면 노드 수가 아니다(플랫폼 C3_CONVERT가 계산).
#     FACES  = 요소 수(대체 경로 elements.csv의 행 수). 면 수가 아니다.
#     UNIT   = 항상 빈 값(26.1 단위 조회 명령은 확인되지 않아 조회하지 않는다 — 단위는 플랫폼이 표시 설정에서 정한다)
#     DISP   = ON(변위 있음) | OFF(INCLUDE_DISP 0) | SKIPPED_NODES(사용 노드가 DISP_MAX_NODES 초과) | NONE(변위 없음·조회 실패)
#     DISP_REASON = DISP=NONE일 때만(120자 이내)   DISP_MISSING_FRAMES = DISP=ON일 때 변위를 못 읽은 프레임 수
#     SCOPE  = ALL(전체) | COMPS(COMPS로 표시 부품만 — 요소 조회를 displayed로 줄였을 때)
#   nodes.csv           node_id,x,y,z   (외부 면에 쓰인 노드, 첫 프레임 좌표 mm, 이후 프레임 값의 행 순서)
#   faces.csv           elem_id,n1,n2,n3,n4   (외부 면: 쉘은 요소 그대로, 솔리드는 자유 면. 삼각형은 n4 비움)
#   elements.csv        elem_id,config,n1..n8   (대체: 외부 면 조회가 안 되면 요소 연결 전체 — 플랫폼 C3_CONVERT가 외부 면을 계산.
#                       config = HyperView 요소 구성 103 tria3·104 quad4·204 tetra4·205 pyramid5·206 penta6·208 hexa8,
#                       2차 요소 106 tria6·108 quad8·210 tetra10·213 pyramid13·215 penta15·220 hexa20은 n1..n8 중 꼭짓점만 쓴다)
#   frame_<out_idx 5자리>.csv   value[,dx,dy,dz]   (nodes.csv 행 순서, 값 없음 = 빈 칸)
#   frame 파일 헤더는 첫 프레임에서 변위 유무를 판정한 뒤 정해서 모든 프레임이 같다(`value` 또는 `value,dx,dy,dz`).
# 프레임 샘플링(결정적): 전체 T ≤ MAX_FRAMES면 전부, 초과면 src_k = round(k·(T−1)/(MAX_FRAMES−1)) (첫·끝 포함, 중복 제거)
# 변위가 없거나 조회가 실패해도 스칼라(contour.value)만으로 계속한다(DISP=NONE). 스칼라 조회 실패만 EXTRACT_ERROR다.
# 단독 실행(extract_settings.tcl 없음)은 안내를 출력하고 끝낸다 — 플랫폼 작업 폴더(_cache/contour3d/<키>/extract)에서 실행한다.

# ------------------------------------------------------------------------------
# 1. 설정 — 플랫폼이 만든 extract_settings.tcl: H3D_PATH OUTDIR FIELD DCOMP AVGMODE MAX_FRAMES INCLUDE_DISP COMPS DISP_MAX_NODES
#    (COMPS·DISP_MAX_NODES가 없는 예전 설정 파일이면 기본값 {}·0 = 검사 안 함)
# ------------------------------------------------------------------------------
set _cfg [file join [file dirname [info script]] extract_settings.tcl]
if {![file exists $_cfg]} {
    puts "contour_extract: extract_settings.tcl not found - run from the platform job folder (_cache/contour3d/<key>/extract)."
    puts "contour_extract: extract_settings.tcl 없음 - 플랫폼 작업 폴더(_cache/contour3d/<키>/extract)에서 실행하세요."
    catch { exit }
    return
}
set COMPS [list]
set DISP_MAX_NODES 0
# 결과 종류가 코너(요소 노드) 값이고 AVGMODE가 비면 노드 조회(contour.value)가 비는 현장 사례(v0.2.12 CornerStress) → 기본 평균 방식.
# extract_settings.tcl이 AVGMODE_DEFAULT를 정하면 그 값을 쓴다(빈 문자열 = 명시 안 함).
set AVGMODE_DEFAULT simple
source $_cfg

set EX_FRAMES [list]
set EX_UNIT ""
set EX_NODES 0
set EX_FACES 0
set EX_TOTAL 0
set EX_DISP [expr {$INCLUDE_DISP ? "ON" : "OFF"}]
set EX_DISP_REASON ""
set EX_DISP_MISSING 0
set EX_SCOPE ALL

proc ex_clean {s} {
    return [string map [list "|" "/" "\r" " " "\n" " "] $s]
}

proc ex_finish {status {msg ""}} {
    global OUTDIR EX_FRAMES EX_UNIT EX_NODES EX_FACES EX_TOTAL FIELD DCOMP AVGMODE EX_DISP EX_DISP_REASON EX_DISP_MISSING EX_SCOPE
    catch {
        set fh [open [file join $OUTDIR extract_result.txt] w]
        fconfigure $fh -encoding utf-8 -translation lf
        puts $fh "# contour_extract 1"
        puts $fh "STATUS=$status"
        if {$msg ne ""} { puts $fh "MESSAGE=[ex_clean $msg]" }
        puts $fh "UNIT=[ex_clean $EX_UNIT]"
        puts $fh "FIELD=[ex_clean $FIELD]"
        puts $fh "DCOMP=[ex_clean $DCOMP]"
        puts $fh "AVGMODE=[ex_clean $AVGMODE]"
        puts $fh "NODES=$EX_NODES"
        puts $fh "FACES=$EX_FACES"
        puts $fh "FRAMES_TOTAL=$EX_TOTAL"
        puts $fh "DISP=$EX_DISP"
        if {$EX_DISP eq "NONE"} { puts $fh "DISP_REASON=[string range [ex_clean $EX_DISP_REASON] 0 119]" }
        if {$EX_DISP eq "ON"} { puts $fh "DISP_MISSING_FRAMES=$EX_DISP_MISSING" }
        puts $fh "SCOPE=$EX_SCOPE"
        foreach f $EX_FRAMES { puts $fh "FRAME=[join $f |]" }
        close $fh
    }
    catch { exit }
}

proc ex_open {name} {
    global OUTDIR
    set fh [open [file join $OUTDIR $name] w]
    fconfigure $fh -encoding utf-8 -translation lf
    return $fh
}

# ------------------------------------------------------------------------------
# 2. 클라이언트 초기화 및 모델/결과 로드(contour_capture.tcl 2절과 같은 코드)
# ------------------------------------------------------------------------------
proc relall {} {
    foreach h {hvSess hvProj hvPage hvWin hvPost hvModel hvResult hvQuery hvSel hvIter} {
        if {[info commands $h] ne ""} { catch {$h ReleaseHandle} ; catch {rename $h ""} }
    }
}

relall
catch { hwc delete client }

if {[catch { hwc open animation modelandresult "$H3D_PATH" "$H3D_PATH" } err]} {
    ex_finish OPEN_ERROR $err
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
    ex_finish OPEN_ERROR $err
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
set EX_TOTAL $nsim

# ------------------------------------------------------------------------------
# 3. 컨투어(Result Scalar) 로드(contour_capture.tcl 4절과 같은 코드)
# ------------------------------------------------------------------------------
if {$FIELD ne ""} {
    set cmd "result scalar load type= \"$FIELD\""
    if {$DCOMP ne ""} { append cmd " component= \"$DCOMP\"" }
    if {$AVGMODE eq "" && $AVGMODE_DEFAULT ne ""} { set AVGMODE $AVGMODE_DEFAULT }
    if {$AVGMODE ne ""} { append cmd " avgmode= $AVGMODE" }
    append cmd " displayed=true"
    if {[catch { hwc {*}$cmd } err]} {
        if {[catch { hwc result scalar load type= "$FIELD" displayed=true } err2]} {
            ex_finish FIELD_ERROR $err2
            return
        }
        set AVGMODE ""
    }
}
# UNIT: 조회하지 않는다(C3F-14 — 26.1에서 `result scalar unit`이 오류 문구를 돌려줘 단위 자리에 들어갔다). EX_UNIT은 늘 빈 값.

# ------------------------------------------------------------------------------
# 3-1. 부품 이름(COMPS) — 조립 결과 범위 줄이기. contour_capture.tcl 5절과 같은 명령(hide all → show 부품).
#      요소 조회만 5절에서 `displayed`로 하고, 실패하거나 0건이면 전체로 폴백(SCOPE=ALL, 플랫폼이 경고)
# ------------------------------------------------------------------------------
set use_comps 0
if {[llength $COMPS] > 0} {
    catch { hwc hide component all }
    foreach comp $COMPS {
        catch { hwc show component "$comp" }
    }
    set use_comps 1
}

# ------------------------------------------------------------------------------
# 4. 프레임 샘플링(결정적)
# ------------------------------------------------------------------------------
set picks [list]
if {$nsim <= $MAX_FRAMES || $MAX_FRAMES < 2} {
    for {set k 0} {$k < $nsim} {incr k} { lappend picks $k }
} else {
    set prev -1
    for {set k 0} {$k < $MAX_FRAMES} {incr k} {
        set s [expr {int(round(double($k) * ($nsim - 1) / ($MAX_FRAMES - 1)))}]
        if {$s != $prev} { lappend picks $s ; set prev $s }
    }
}

# ------------------------------------------------------------------------------
# 5. 외부 면(자유 면) → faces.csv·nodes.csv. 조회가 안 되면 요소 연결 전체(elements.csv) — 플랫폼이 외부 면을 계산
# ------------------------------------------------------------------------------
proc ex_query {fields setType {sel "all"}} {
    # 반환: 행 목록(각 행 = 필드 값 목록). 선택 집합 = sel(기본 모든 엔터티). 오류여도 핸들을 정리한 뒤 다시 던진다(폴백 조회 가능)
    set rows [list]
    set sid ""
    set rc [catch {
        hvModel GetQueryCtrlHandle hvQuery
        set sid [hvModel AddSelectionSet $setType]
        hvModel GetSelectionSetHandle hvSel $sid
        hvSel Add $sel
        hvQuery SetSelectionSet $sid
        hvQuery SetQuery $fields
        hvQuery GetIteratorHandle hvIter
        for {hvIter First} {[hvIter Valid]} {hvIter Next} { lappend rows [hvIter GetDataList] }
    } err opts]
    catch { hvIter ReleaseHandle } ; catch { rename hvIter "" }
    catch { hvSel ReleaseHandle } ; catch { rename hvSel "" }
    if {$sid ne ""} { catch { hvModel RemoveSelectionSet $sid } }
    catch { hvQuery ReleaseHandle } ; catch { rename hvQuery "" }
    if {$rc} { return -options $opts $err }
    return $rows
}

# 변위 행 판정: 3성분이고 첫 성분이 비어 있지 않으면 유효
proc ex_disp_valid {d} {
    return [expr {[llength $d] == 3 && [lindex $d 0] ne ""}]
}

catch { hvResult SetCurrentSimulation [lindex $picks 0] }
set node_rows [list]
if {[catch { set node_rows [ex_query "node.id node.coords" node] } err]} {
    ex_finish EXTRACT_ERROR $err
    return
}
set elem_rows [list]
set elem_fields "element.id element.config element.connectivity"
if {$use_comps} {
    # 26.1에서 `hvSel Add "displayed"`가 되는지는 현장 확인 항목 — 오류이거나 0건이면 전체로 다시 조회한다
    if {![catch { set elem_rows [ex_query $elem_fields element displayed] }] && [llength $elem_rows] > 0} {
        set EX_SCOPE COMPS
    } else {
        set elem_rows [list]
        catch { hwc show component all }
    }
}
if {$EX_SCOPE ne "COMPS"} {
    if {[catch { set elem_rows [ex_query $elem_fields element] } err]} {
        ex_finish EXTRACT_ERROR $err
        return
    }
}
# 요소 연결 전체를 쓴다(대체 경로 — 외부 면 계산은 플랫폼). n1..n8만 쓴다: 2차 요소(106·108·210·213·215·220)는 꼭짓점이 먼저 오므로
# 플랫폼이 1차 요소로 취급한다(중간 노드는 쓰지 않는다).
set fh [ex_open elements.csv]
puts $fh "elem_id,config,n1,n2,n3,n4,n5,n6,n7,n8"
foreach r $elem_rows {
    set conn [lindex $r 2]
    set vals [list [lindex $r 0] [lindex $r 1]]
    for {set i 0} {$i < 8} {incr i} { lappend vals [lindex $conn $i] }
    puts $fh [join $vals ,]
}
close $fh
# 사용 노드 = 요소 꼭짓점(2차 요소의 중간 노드는 제외 — 면·값 모두 꼭짓점만 쓴다)
proc ex_vcount {config} {
    switch -- $config {
        103 - 106 { return 3 }
        104 - 108 - 204 - 210 { return 4 }
        205 - 213 { return 5 }
        206 - 215 { return 6 }
        208 - 220 { return 8 }
    }
    return 8
}
set used [dict create]
foreach r $elem_rows {
    set vc [ex_vcount [lindex $r 1]]
    foreach n [lrange [lindex $r 2] 0 [expr {$vc - 1}]] { dict set used $n 1 }
}
set order [list]
set fh [ex_open nodes.csv]
puts $fh "node_id,x,y,z"
foreach r $node_rows {
    set nid [lindex $r 0]
    if {![dict exists $used $nid]} { continue }
    set c [lindex $r 1]
    puts $fh "$nid,[lindex $c 0],[lindex $c 1],[lindex $c 2]"
    lappend order $nid
}
close $fh
set EX_NODES [llength $order]
set EX_FACES [llength $elem_rows]

# ------------------------------------------------------------------------------
# 5-1. 변위 판정(§9.4) — 한 번만 정하고 헤더·이후 프레임을 일관되게 쓴다. 변위가 없어도 스칼라만으로 계속한다
# ------------------------------------------------------------------------------
set first_disp [dict create]
set have_first_disp 0
if {$INCLUDE_DISP} {
    if {$DISP_MAX_NODES > 0 && $EX_NODES > $DISP_MAX_NODES} {
        # 1. 노드 상한: 읽지 않는다
        set INCLUDE_DISP 0
        set EX_DISP SKIPPED_NODES
    } else {
        # 2. 사전 확인(선택, best-effort): 결과 종류 목록이 조회되고 displacement가 하나도 없으면 읽지 않는다.
        #    26.1 동작은 미확인 — 오류·빈 목록이면 건너뛰고 3으로 판정한다(시간을 아낄 뿐, 결과를 정하지 않음)
        set dts ""
        if {![catch { hvResult GetDataTypeList $sub } dts] && [llength $dts] > 0} {
            set found 0
            foreach dt $dts {
                if {[string match -nocase *displacement* $dt]} { set found 1 ; break }
            }
            if {!$found} {
                set INCLUDE_DISP 0
                set EX_DISP NONE
                set EX_DISP_REASON "no displacement result type"
            }
        }
    }
}
if {$INCLUDE_DISP} {
    # 3. 첫 프레임에서 한 번 조회: 오류·0행·유효 행 없음이면 스칼라만으로 계속(DISP=NONE)
    set probe_err ""
    set probe_rows [list]
    if {[catch { set probe_rows [ex_query "node.id node.displacement" node] } probe_err]} {
        set INCLUDE_DISP 0
        set EX_DISP NONE
        set EX_DISP_REASON $probe_err
    } else {
        foreach r $probe_rows {
            if {[ex_disp_valid [lindex $r 1]]} { dict set first_disp [lindex $r 0] [lindex $r 1] }
        }
        if {[dict size $first_disp] == 0} {
            set INCLUDE_DISP 0
            set EX_DISP NONE
            set EX_DISP_REASON "empty"
        } else {
            set have_first_disp 1
        }
    }
}

# ------------------------------------------------------------------------------
# 6. 프레임마다 노드 스칼라(평균 방식은 3절 설정) + 선택 변위 → frame_<idx>.csv
#    스칼라 조회 실패 = EXTRACT_ERROR. 변위는 첫 프레임에서 있었는데 뒤 프레임에서 못 읽으면 그 프레임의 dx,dy,dz를 빈 칸으로 쓰고
#    계속한다(DISP_MISSING_FRAMES — 변환기가 변위 전체를 뺀다)
# ------------------------------------------------------------------------------
set out_idx 0
foreach src $picks {
    if {[catch { hvResult SetCurrentSimulation $src } err]} {
        ex_finish EXTRACT_ERROR $err
        return
    }
    set t ""
    catch { hvResult GetSimulationLabel $sub $src } t
    set vals [dict create]
    if {[catch {
        foreach r [ex_query "node.id contour.value" node] { dict set vals [lindex $r 0] [lindex $r 1] }
    } err]} {
        ex_finish EXTRACT_ERROR $err
        return
    }
    if {$out_idx == 0 && $FIELD ne ""} {
        # 첫 프레임 값이 전부 비면: 평균 방식을 simple로 명시해 다시 로드·조회(한 번). 그래도 비면 값 없는 결과로 실패 처리한다
        set nonempty 0
        foreach nid $order { if {[dict exists $vals $nid] && [dict get $vals $nid] ne ""} { incr nonempty ; break } }
        if {$nonempty == 0 && $AVGMODE ne "simple"} {
            set rcmd "result scalar load type= \"$FIELD\""
            if {$DCOMP ne ""} { append rcmd " component= \"$DCOMP\"" }
            append rcmd " avgmode= simple displayed=true"
            if {![catch { hwc {*}$rcmd }]} {
                set AVGMODE simple
                catch { hvResult SetCurrentSimulation $src }
                set vals [dict create]
                catch { foreach r [ex_query "node.id contour.value" node] { dict set vals [lindex $r 0] [lindex $r 1] } }
                foreach nid $order { if {[dict exists $vals $nid] && [dict get $vals $nid] ne ""} { incr nonempty ; break } }
            }
        }
        if {$nonempty == 0} {
            ex_finish FIELD_ERROR "contour.value is empty for all nodes (field=$FIELD dcomp=$DCOMP avgmode=$AVGMODE)"
            return
        }
    }
    set disp [dict create]
    if {$INCLUDE_DISP} {
        if {$out_idx == 0 && $have_first_disp} {
            set disp $first_disp
        } else {
            set drows [list]
            if {![catch { set drows [ex_query "node.id node.displacement" node] }]} {
                foreach r $drows {
                    if {[ex_disp_valid [lindex $r 1]]} { dict set disp [lindex $r 0] [lindex $r 1] }
                }
            }
            if {[dict size $disp] == 0} { incr EX_DISP_MISSING }
        }
    }
    set fh [ex_open [format "frame_%05d.csv" $out_idx]]
    puts $fh [expr {$INCLUDE_DISP ? "value,dx,dy,dz" : "value"}]
    foreach nid $order {
        set v [expr {[dict exists $vals $nid] ? [dict get $vals $nid] : ""}]
        if {$INCLUDE_DISP} {
            set d [expr {[dict exists $disp $nid] ? [dict get $disp $nid] : [list "" "" ""]}]
            puts $fh "$v,[lindex $d 0],[lindex $d 1],[lindex $d 2]"
        } else {
            puts $fh $v
        }
    }
    close $fh
    lappend EX_FRAMES [list $out_idx $src [ex_clean $t]]
    incr out_idx
}

ex_finish OK
