"""시험 데이터: 원본 update_parameter_file 사본(1_CREATE_TRAINING_DATA/FUNC/1_create_tpl_file.py:127-193, Ver.0.0.6).

V2-TD-3 골든 비교 전용 — 플랫폼 코드에서 import하지 않는다. 내용은 원본 그대로(수정 금지).
"""
import re


def update_parameter_file(template_file, output_file, arr_dict_rows_data, cad_filename):

    with open(template_file, "r", encoding="utf-8") as fp:
        text = fp.read()

    text = text.lstrip('\ufeff\r\n\t ')

    # ── dir_file_prt 라인 → cad_filename(파일명만, 상대경로)으로 교체 ──────────
    text = re.sub(
        r'dir_file_prt\s*=\s*r"[^"]*"',
        f'dir_file_prt = r"./{cad_filename}"',
        text
    )    
    # parameter(...) 라인 생성
    parameter_lines = []
    for idx, row_data in enumerate(arr_dict_rows_data.values(), start=1):
        parameter_lines.append(
            f'{{parameter(var_{idx}, '
            f'"{row_data["param"]}", '
            f'{row_data["nominal"]}, '
            f'{row_data["min"]}, '
            f'{row_data["max"]})}}'
        )

    parameter_block = "\n".join(parameter_lines)

    text = re.sub(
        r'(?m)^[^\n]*\{parameter\(.*?\)\}[^\n]*\n?',
        '',
        text
    )

    marker = "#***************************************************************"
    pos = text.find(marker)
    if pos == -1:
        raise ValueError("Cannot find marker")

    text = parameter_block + "\n" + text[pos:]

    # paramitem block 생성
    paramitem_lines = []
    for idx, row_data in enumerate(arr_dict_rows_data.values(), start=1):
        paramitem_lines.append(
            f'   <paramitem Name="{row_data["param"]}" '
            f'NewValue="{{var_{idx}, %3i}}" '
            f'Value="{row_data["nominal"]}"/>'
        )

    paramitem_block = "\n".join(paramitem_lines)

    text = re.sub(
        r'(?m)^[^\n]*<paramitem[^>]*/>[^\n]*\n?',
        '',
        text
    )

    text = text.replace(
        '<Parameters Value="">',
        '<Parameters Value="">\n' + paramitem_block
    )

    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)

    with open(output_file, "w", encoding="utf-8") as fp:
        fp.write(text)

    print(f"Generated : {output_file}")
