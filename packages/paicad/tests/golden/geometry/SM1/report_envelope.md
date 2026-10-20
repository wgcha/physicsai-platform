# Shell morphing envelope report

- schema_version: 2
- engine_version: 0.10.0
- sweep_id: S-86f9877bea58
- steps, depth / width (% of nominal, each direction): 5, 10, 20, 30, 40, 50
- steps, position (mm from nominal, each direction): 1, 2, 3, 5, 8, 10
- stop a direction after 2 consecutive failures
- quality: max_warpage_deg 15.0, max_skew_deg 60.0, max_aspect 5.0, min_jacobian 0.6, min_edge_ratio 0.8, dt_ratio_min 0.8, relative_to_baseline True
- bead: depth_mode keep_angle, position_ref nearest_fixed_edge; fixed transition_mm 6.0
- limit = criterion with the smallest margin (value / threshold) at the first failure, else at the last OK step; limited by 'fixed' = first failure SHELL_FIXED_REGION_VIOLATION

| param | nominal | unit | last OK + | last OK - | first fail + | first fail - | limit + (margin) | limit - (margin) | feasible |
|---|---|---|---|---|---|---|---|---|---|
| CHASSIS_REAR_BEAD_D_1 | 3.0 | % | 0 % | 0 % | 5 % SHELL_FIXED_REGION_VIOLATION | 5 % SHELL_FIXED_REGION_VIOLATION | SHELL_FIXED_REGION_VIOLATION (-) | SHELL_FIXED_REGION_VIOLATION (-) | 3.0 .. 3.0 |
| CHASSIS_REAR_BEAD_D_2 | 4.0 | % | 20 % | 30 % | 30 % GEOM_QUALITY | 40 % GEOM_QUALITY | min_jacobian (0.9957) | max_aspect (0.7811) | 2.8 .. 4.8 |
| CHASSIS_REAR_BEAD_D_3 | 3.0 | % | 30 % | 10 % | 40 % GEOM_QUALITY | 20 % GEOM_QUALITY | min_jacobian (0.9802) | max_aspect (0.7698) | 2.7 .. 3.9 |
| CHASSIS_REAR_BEAD_D_4 | 3.0 | % | 50 % | 10 % | - | 20 % GEOM_QUALITY | min_jacobian (1.0196) | max_aspect (0.7225) | 2.7 .. 4.5 |
| CHASSIS_REAR_BEAD_D_5 | 3.0 | % | 20 % | 10 % | 30 % GEOM_QUALITY | 20 % GEOM_QUALITY | min_jacobian (0.9852) | max_aspect (0.7852) | 2.7 .. 3.6 |
| CHASSIS_REAR_BEAD_U_1 | 80.0 | mm | 0 mm | 0 mm | 1 mm SHELL_FIXED_REGION_VIOLATION | 1 mm GEOM_FEATURE_COLLISION | SHELL_FIXED_REGION_VIOLATION (-) | GEOM_FEATURE_COLLISION (-) | 80.0 .. 80.0 |
| CHASSIS_REAR_BEAD_U_2 | 120.0 | mm | 10 mm | 10 mm | - | - | min_jacobian (1.0196) | min_jacobian (1.0196) | 110.0 .. 130.0 |
| CHASSIS_REAR_BEAD_U_3 | 150.0 | mm | 10 mm | 10 mm | - | - | min_jacobian (1.0196) | min_jacobian (1.0037) | 140.0 .. 160.0 |
| CHASSIS_REAR_BEAD_U_4 | 100.0 | mm | 10 mm | 10 mm | - | - | min_jacobian (1.0196) | min_jacobian (1.0196) | 90.0 .. 110.0 |
| CHASSIS_REAR_BEAD_U_5 | 150.0 | mm | 1 mm | 2 mm | 2 mm GEOM_QUALITY | 3 mm GEOM_QUALITY | max_skew_deg (0.9973) | min_jacobian (0.7823) | 148.0 .. 151.0 |
| CHASSIS_REAR_BEAD_V_1 | 45.0 | mm | 0 mm | 0 mm | 1 mm SHELL_FIXED_REGION_VIOLATION | 1 mm SHELL_FIXED_REGION_VIOLATION | SHELL_FIXED_REGION_VIOLATION (-) | SHELL_FIXED_REGION_VIOLATION (-) | 45.0 .. 45.0 |
| CHASSIS_REAR_BEAD_V_2 | 90.0 | mm | 8 mm | 10 mm | 10 mm GEOM_QUALITY | - | max_skew_deg (0.9922) | min_jacobian (1.0196) | 80.0 .. 98.0 |
| CHASSIS_REAR_BEAD_V_3 | 150.0 | mm | 10 mm | 10 mm | - | - | min_jacobian (1.0196) | min_jacobian (1.0196) | 140.0 .. 160.0 |
| CHASSIS_REAR_BEAD_V_4 | 80.0 | mm | 10 mm | 10 mm | - | - | min_jacobian (1.0196) | min_jacobian (1.0196) | 70.0 .. 90.0 |
| CHASSIS_REAR_BEAD_V_5 | 49.0 | mm | 1 mm | 1 mm | 2 mm GEOM_QUALITY | 2 mm GEOM_QUALITY | min_jacobian (0.9898) | edge_ratio (0.5623) | 48.0 .. 50.0 |
| CHASSIS_REAR_BEAD_W_1 | 20.0 | % | 0 % | 0 % | 5 % GEOM_FEATURE_COLLISION | 5 % SHELL_FIXED_REGION_VIOLATION | GEOM_FEATURE_COLLISION (-) | SHELL_FIXED_REGION_VIOLATION (-) | 20.0 .. 20.0 |
| CHASSIS_REAR_BEAD_W_2 | 12.0 | % | 50 % | 10 % | - | 20 % GEOM_QUALITY | min_jacobian (1.0095) | min_jacobian (0.9241) | 10.8 .. 18.0 |
| CHASSIS_REAR_BEAD_W_3 | 10.0 | % | 50 % | 10 % | - | 20 % GEOM_FEATURE_COLLISION | min_jacobian (1.0196) | GEOM_FEATURE_COLLISION (-) | 9.0 .. 15.0 |
| CHASSIS_REAR_BEAD_W_4 | 30.0 | % | 40 % | 10 % | 50 % GEOM_QUALITY | 20 % GEOM_QUALITY | max_aspect (0.9766) | min_jacobian (0.9579) | 27.0 .. 42.0 |
| CHASSIS_REAR_BEAD_W_5 | 10.0 | % | 30 % | 5 % | 40 % GEOM_QUALITY | 10 % GEOM_QUALITY | min_jacobian (0.2931) | min_jacobian (0.9882) | 9.5 .. 13.0 |
