# HyperView Tcl API 가짜(시험 전용) — `tclsh hw_tcl_stub.tcl <contour_extract.tcl>`로 추출 TCL의 제어 흐름을 실제 Tcl 인터프리터로 검증한다.
# 실제 hw 명령(hwc·hwi·hv*)의 최소 부분집합만 흉내 낸다. 시나리오는 환경변수:
#   STUB_NSIM(기본 5)        시뮬레이션(프레임) 수
#   STUB_DTL = list(기본, displacement 포함) | nodisp(포함 안 함) | error(명령 오류) | empty(빈 목록)
#   STUB_DISP = ok(기본) | error(오류 문구) | empty(빈 값 행) | none0(0행)
#   STUB_DISP_FAIL_AT=<sim>  그 시뮬레이션에서만 변위 조회 오류(첫 프레임 이후 누락 시험)
#   STUB_DISPLAYED = ok(기본: e1만) | error | empty(0건)
#   STUB_FIELD_FAIL=1        result scalar load 실패 / STUB_OPEN_FAIL=1  h3d 열기 실패 / STUB_SCALAR_FAIL=1  contour.value 조회 오류
# 노드 1~6(+미사용 99), 요소 e1(노드 1,2,5,4)·e2(노드 2,3,6,5) 쿼드 쉘. e1 = 부품 "A", e2 = 부품 "B".
set ::CUR 0
set ::SELN 0
array set ::SETTYPE {}
array set ::SELWHAT {}
set ::QSET ""
set ::QFIELDS ""
set ::SHOWN [list]
set ::HID 0
proc env_or {k d} { if {[info exists ::env($k)]} { return $::env($k) } ; return $d }

proc mk {name kind} { proc ::$name {args} "handle $kind \$args" }

proc hwc {args} {
    set a [string trim [join $args " "]]
    if {[string match "open animation modelandresult*" $a]} {
        if {[env_or STUB_OPEN_FAIL 0]} { error "cannot open h3d" }
        return
    }
    if {[string match "result scalar load*" $a]} {
        if {[env_or STUB_FIELD_FAIL 0]} { error "no such result type" }
        return
    }
    if {$a eq "hide component all"} { set ::HID 1 ; set ::SHOWN [list] ; return }
    if {$a eq "show component all"} { set ::HID 0 ; return }
    if {[string match "show component *" $a]} { lappend ::SHOWN [lindex $args 2] ; return }
    return
}
proc hwi {args} { mk [lindex $args 1] sess }

proc handle {kind argv} {
    set m [lindex $argv 0]
    switch $kind {
        sess  { if {$m eq "GetProjectHandle"} { mk [lindex $argv 1] proj } }
        proj  { if {$m eq "GetActivePage"} { return 1 } ; if {$m eq "GetPageHandle"} { mk [lindex $argv 1] page } }
        page  { if {$m eq "GetActiveWindow"} { return 1 } ; if {$m eq "GetWindowHandle"} { mk [lindex $argv 1] win } }
        win   { if {$m eq "GetClientHandle"} { mk [lindex $argv 1] post } }
        post  { if {$m eq "GetActiveModel"} { return 1 } ; if {$m eq "GetModelHandle"} { mk [lindex $argv 1] model } }
        model {
            switch $m {
                GetResultCtrlHandle { mk [lindex $argv 1] result }
                GetQueryCtrlHandle { mk [lindex $argv 1] query }
                AddSelectionSet { incr ::SELN ; set ::SETTYPE($::SELN) [lindex $argv 1] ; return $::SELN }
                GetSelectionSetHandle { set ::CURSEL [lindex $argv 2] ; mk [lindex $argv 1] sel }
                RemoveSelectionSet { return }
            }
        }
        sel   { if {$m eq "Add"} {
                    set what [lindex $argv 1]
                    if {$what eq "displayed" && [env_or STUB_DISPLAYED ok] eq "error"} { error "invalid selection \"displayed\"" }
                    set ::SELWHAT($::CURSEL) $what
                } }
        result {
            switch $m {
                GetCurrentSubcase { return 1 }
                GetSubcaseList { return {1} }
                GetNumberOfSimulations { return [env_or STUB_NSIM 5] }
                SetCurrentSimulation { set ::CUR [lindex $argv 1] }
                GetSimulationLabel { return "Time = [expr {[lindex $argv 2] * 0.1}]" }
                GetDataTypeList {
                    switch [env_or STUB_DTL list] {
                        error { error "invalid command" }
                        empty { return {} }
                        nodisp { return {Stress Strain} }
                        default { return {Stress Displacement Strain} }
                    }
                }
            }
        }
        query {
            switch $m {
                SetSelectionSet { set ::QSET [lindex $argv 1] }
                SetQuery { set ::QFIELDS [lindex $argv 1] }
                GetIteratorHandle { set ::ROWS [stub_rows] ; set ::IDX 0 ; mk [lindex $argv 1] iter }
            }
        }
        iter {
            switch $m {
                First { set ::IDX 0 }
                Valid { return [expr {$::IDX < [llength $::ROWS]}] }
                Next { incr ::IDX }
                GetDataList { return [lindex $::ROWS $::IDX] }
            }
        }
    }
}

proc stub_rows {} {
    set rows [list]
    set nodes {1 2 3 4 5 6 99}
    set coords {1 {0 0 0} 2 {1 0 0} 3 {2 0 0} 4 {0 1 0} 5 {1 1 0} 6 {2 1 0} 99 {9 9 9}}
    switch -- $::QFIELDS {
        "node.id node.coords" { foreach n $nodes { lappend rows [list $n [dict get $coords $n]] } }
        "element.id element.config element.connectivity" {
            set what [expr {[info exists ::SELWHAT($::QSET)] ? $::SELWHAT($::QSET) : "all"}]
            if {$what eq "displayed"} {
                if {[env_or STUB_DISPLAYED ok] eq "empty"} { return [list] }
                if {[lsearch -exact $::SHOWN A] >= 0} { lappend rows [list 1 104 {1 2 5 4}] }
                if {[lsearch -exact $::SHOWN B] >= 0} { lappend rows [list 2 104 {2 3 6 5}] }
            } else {
                lappend rows [list 1 104 {1 2 5 4}] [list 2 104 {2 3 6 5}]
            }
        }
        "node.id contour.value" {
            if {[env_or STUB_SCALAR_FAIL 0]} { error "contour query failed" }
            foreach n $nodes { lappend rows [list $n [expr {$n * ($::CUR + 1)}]] }
        }
        "node.id node.displacement" {
            set mode [env_or STUB_DISP ok]
            if {$mode eq "error" || $::CUR == [env_or STUB_DISP_FAIL_AT -1]} {
                error "Invalid command syntax: displacement not available"
            }
            if {$mode eq "none0"} { return [list] }
            foreach n $nodes {
                if {$mode eq "empty"} { lappend rows [list $n [list "" "" ""]] } else { lappend rows [list $n [list 0.0 0.0 [expr {0.01 * $::CUR}]]] }
            }
        }
    }
    return $rows
}

if {$argc < 1} { puts "usage: tclsh hw_tcl_stub.tcl contour_extract.tcl" ; exit 2 }
source [lindex $argv 0]
