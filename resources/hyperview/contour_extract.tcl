# ==============================================================================
# HyperView 결과 3D 컨투어 추출(배치) — contour_capture.tcl의 형제 파일(geometry-view.md §13.3)
# ==============================================================================
# PhysicsAI 플랫폼이 CONTOUR_3D 작업(C3_EXTRACT)에서 `hw -clientconfig hwpost.dat -b -tcl contour_extract.tcl`로 실행한다.
# contour_capture.tcl의 동작은 바꾸지 않는다. h3d 열기·핸들·결과 종류/성분/평균 방식 절은 contour_capture.tcl과 같은 코드(복사 재사용).
# 출력 계약(OUTDIR, UTF-8, LF — 플랫폼이 이 파일들로 판정한다. hw 명령 이름은 현장 버전 확인 후 이 TCL에서만 바꾼다):
#   extract_result.txt  # contour_extract 1 / STATUS=OK|OPEN_ERROR|FIELD_ERROR|EXTRACT_ERROR / MESSAGE= / UNIT= / FIELD= DCOMP= AVGMODE=
#                       / NODES= FACES= FRAMES_TOTAL= / FRAME=<out_idx>|<src_idx>|<time>
#   nodes.csv           node_id,x,y,z   (외부 면에 쓰인 노드, 첫 프레임 좌표 mm, 이후 프레임 값의 행 순서)
#   faces.csv           elem_id,n1,n2,n3,n4   (외부 면: 쉘은 요소 그대로, 솔리드는 자유 면. 삼각형은 n4 비움)
#   elements.csv        elem_id,config,n1..n8   (대체: 외부 면 조회가 안 되면 요소 연결 전체 — 플랫폼 C3_CONVERT가 외부 면을 계산.
#                       config = HyperView 요소 구성 103 tria3·104 quad4·204 tetra4·205 pyramid5·206 penta6·208 hexa8)
#   frame_<out_idx 5자리>.csv   value[,dx,dy,dz]   (nodes.csv 행 순서, 값 없음 = 빈 칸)
# 프레임 샘플링(결정적): 전체 T ≤ MAX_FRAMES면 전부, 초과면 src_k = round(k·(T−1)/(MAX_FRAMES−1)) (첫·끝 포함, 중복 제거)

# ------------------------------------------------------------------------------
# 1. 설정 — 플랫폼이 만든 extract_settings.tcl: H3D_PATH OUTDIR FIELD DCOMP AVGMODE MAX_FRAMES INCLUDE_DISP
# ------------------------------------------------------------------------------
source [file join [file dirname [info script]] extract_settings.tcl]

set EX_FRAMES [list]
set EX_UNIT ""
set EX_NODES 0
set EX_FACES 0
set EX_TOTAL 0

proc ex_clean {s} {
    return [string map [list "|" "/" "\r" " " "\n" " "] $s]
}

proc ex_finish {status {msg ""}} {
    global OUTDIR EX_FRAMES EX_UNIT EX_NODES EX_FACES EX_TOTAL FIELD DCOMP AVGMODE
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
    if {$AVGMODE ne ""} { append cmd " avgmode= $AVGMODE" }
    append cmd " displayed=true"
    if {[catch { hwc {*}$cmd } err]} {
        if {[catch { hwc result scalar load type= "$FIELD" displayed=true } err2]} {
            ex_finish FIELD_ERROR $err2
            return
        }
    }
}
catch { hwc result scalar unit } EX_UNIT

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
proc ex_query {fields setType} {
    # 반환: 행 목록(각 행 = 필드 값 목록). 선택 집합 = 모든 엔터티
    set rows [list]
    hvModel GetQueryCtrlHandle hvQuery
    set sid [hvModel AddSelectionSet $setType]
    hvModel GetSelectionSetHandle hvSel $sid
    hvSel Add "all"
    hvQuery SetSelectionSet $sid
    hvQuery SetQuery $fields
    hvQuery GetIteratorHandle hvIter
    for {hvIter First} {[hvIter Valid]} {hvIter Next} { lappend rows [hvIter GetDataList] }
    catch { hvIter ReleaseHandle } ; catch { rename hvIter "" }
    catch { hvSel ReleaseHandle } ; catch { rename hvSel "" }
    catch { hvModel RemoveSelectionSet $sid }
    catch { hvQuery ReleaseHandle } ; catch { rename hvQuery "" }
    return $rows
}

catch { hvResult SetCurrentSimulation [lindex $picks 0] }
set node_rows [list]
if {[catch { set node_rows [ex_query "node.id node.coords" node] } err]} {
    ex_finish EXTRACT_ERROR $err
    return
}
set elem_rows [list]
if {[catch { set elem_rows [ex_query "element.id element.config element.connectivity" element] } err]} {
    ex_finish EXTRACT_ERROR $err
    return
}
# 요소 연결 전체를 쓴다(대체 경로 — 외부 면 계산은 플랫폼). 2D 요소(3·4절점)는 faces.csv에도 그대로 쓴다.
set fh [ex_open elements.csv]
puts $fh "elem_id,config,n1,n2,n3,n4,n5,n6,n7,n8"
foreach r $elem_rows {
    set conn [lindex $r 2]
    set vals [list [lindex $r 0] [lindex $r 1]]
    for {set i 0} {$i < 8} {incr i} { lappend vals [lindex $conn $i] }
    puts $fh [join $vals ,]
}
close $fh
set used [dict create]
foreach r $elem_rows {
    foreach n [lindex $r 2] { dict set used $n 1 }
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
# 6. 프레임마다 노드 스칼라(평균 방식은 3절 설정) + 선택 변위 → frame_<idx>.csv
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
    set disp [dict create]
    if {[catch {
        foreach r [ex_query "node.id contour.value" node] { dict set vals [lindex $r 0] [lindex $r 1] }
        if {$INCLUDE_DISP} {
            foreach r [ex_query "node.id node.displacement" node] { dict set disp [lindex $r 0] [lindex $r 1] }
        }
    } err]} {
        ex_finish EXTRACT_ERROR $err
        return
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
