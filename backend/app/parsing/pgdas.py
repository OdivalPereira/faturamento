import os
import re
import pdfplumber
import json
from datetime import datetime
from ..database.db import get_db

def parse_currency(val_str):
    if not val_str: return 0.0
    try:
        clean = val_str.replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
        return float(clean)
    except:
        return 0.0

def get_empresa_id_by_cnpj(conn, cnpj):
    clean_target = re.sub(r'\D', '', cnpj)
    if not clean_target: return None
    
    # Simple search for portable app
    row = conn.execute("SELECT id FROM empresas WHERE REPLACE(REPLACE(REPLACE(cnpj_cpf, '.', ''), '/', ''), '-', '') = ?", (clean_target,)).fetchone()
    if row: return row[0]
    
    # Fallback root
    raiz = clean_target[:8]
    row = conn.execute("SELECT id FROM empresas WHERE REPLACE(REPLACE(REPLACE(cnpj_cpf, '.', ''), '/', ''), '-', '') LIKE ?", (f"{raiz}%",)).fetchone()
    if row: return row[0]
    
    return None

def detect_filiais(text_content):
    filiais_section = re.search(r'1\.1 CNPJ das filiais presentes nesta declaração:\s*(.+?)(?=\.\s*2\.|$)', text_content, re.DOTALL)
    if filiais_section:
        content = filiais_section.group(1).strip()
        if 'Nenhuma' in content or not content: return []
        cnpjs = re.findall(r'(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})', content)
        return cnpjs
    return []

def extract_estabelecimentos(text_content):
    estabelecimentos = []
    blocks = re.split(r'CNPJ Estabelecimento:', text_content)
    for block in blocks[1:]:
        cnpj_match = re.search(r'(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})', block)
        if cnpj_match:
            cnpj = cnpj_match.group(1)
            valor = 0.0
            patterns = [
                r'Totais do [Ee]stabelecimento\s*Valor Informado:\s*R?\$?\s*([\d\.]+,\d{2})',
                r'Totais do [Ee]stabelecimento[^\d]*([\d\.]+,\d{2})',
                r'Receita Bruta Informada:\s*R\$\s*([\d\.]+,\d{2})',
                r'Receita Bruta Informada[^\d]*([\d\.]+,\d{2})',
            ]
            for pattern in patterns:
                valor_match = re.search(pattern, block)
                if valor_match:
                    valor = parse_currency(valor_match.group(1))
                    break
            if valor > 0:
                estabelecimentos.append({'cnpj': cnpj, 'valor': valor})
    return estabelecimentos

def extract_historico_consolidado(text_content):
    historico = []
    # Support optional R$, spaces, and . or / separators
    history_iter = re.finditer(r'(\d{2}[/.]\d{4})\s*R?\$?\s*([\d\.]*,\d{2})', text_content)
    for h in history_iter:
        mes_ano = h.group(1).replace('.', '/')
        h_mes = int(mes_ano[:2])
        h_year = int(mes_ano[3:])
        h_val = parse_currency(h.group(2))
        if 2010 < h_year < 2040 and h_val > 0:
            historico.append({'mes': h_mes, 'ano': h_year, 'valor': h_val})
    return historico

def process_pgdas_pdf(file_path, conn):
    filename = os.path.basename(file_path)
    res_dict = {"status": "skipped", "reason": "Unknown", "records": 0}
    try:
        with pdfplumber.open(file_path) as pdf:
            text_content = "\n".join([page.extract_text() or "" for page in pdf.pages])
            
            # CNPJ Matriz - more flexible search
            cnpj_match = re.search(r'CNPJ Matriz:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})', text_content)
            main_cnpj = None
            if not cnpj_match:
                # Fallback: find any CNPJ and see if it's in our database
                all_cnpjs = re.findall(r'(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})', text_content)
                for candidate in all_cnpjs:
                    if get_empresa_id_by_cnpj(conn, candidate):
                        main_cnpj = candidate
                        break
                if not main_cnpj:
                    res_dict["reason"] = "Não foi possível identificar um CNPJ cadastrado"
                    return res_dict
            else:
                main_cnpj = cnpj_match.group(1)
            
            empresa_id = get_empresa_id_by_cnpj(conn, main_cnpj)
            if not empresa_id:
                res_dict["reason"] = f"CNPJ {main_cnpj} não encontrado no banco de dados"
                return res_dict

            # PA Match - support (PA) suffix and . separator
            pa_match = re.search(r'Período de Apuração(?:\s*\(PA\))?:?\s*(\d{2}[/.]\d{2}[/.]\d{4})', text_content)
            if not pa_match:
                pa_match = re.search(r'Período de Apuração(?:\s*\(PA\))?:?\s*(\d{2}[/.]\d{4})', text_content)
            if not pa_match:
                pa_match = re.search(r'PA:?\s*(\d{2}[/.]\d{4})', text_content)
            
            if not pa_match:
                res_dict["reason"] = "Período de Apuração não identificado"
                return res_dict

            dt_str = pa_match.group(1).replace('.', '/')
            if '/' in dt_str:
                parts = dt_str.split('/')
                if len(parts) == 3: # dd/mm/yyyy
                    pa_month, pa_year = int(parts[1]), int(parts[2])
                else: # mm/yyyy
                    pa_month, pa_year = int(parts[0]), int(parts[1])
            else:
                res_dict["reason"] = "Formato de data inválido"
                return res_dict

            # 1. Base Revenue (Total RPA) - Always extract as baseline
            rpa_patterns = [
                r'2\.6\) Resumo da Declaração\s*Receita Bruta Auferida[^\d\n]*R?\$?\s*([\d\.]*,\d{2})',
                r'Receita Bruta do PA \(RPA\)[^\d\n]*R?\$?\s*([\d\.]*,\d{2})',
                r'Receita Bruta do PA \(RPA\)[^,]*\s*([\d\.]*,\d{2})', # More generic
                r'Receita Bruta Total[^\d\n]*R?\$?\s*([\d\.]*,\d{2})',
                r'Total de Receitas do PA[^\d\n]*R?\$?\s*([\d\.]*,\d{2})',
                r'Receita Bruta Auferida no PA[^\d\n]*R?\$?\s*([\d\.]*,\d{2})',
                r'Valor Informado[^\d\n]*R?\$?\s*([\d\.]*,\d{2})' # More aggressive
            ]
            total_rpa = 0.0
            for pat in rpa_patterns:
                match = re.search(pat, text_content)
                if match:
                    total_rpa = parse_currency(match.group(1))
                    break

            # 2. Extract Establishments (Matriz + Filiais)
            estabelecimentos = extract_estabelecimentos(text_content)
            sum_est = sum(e['valor'] for e in estabelecimentos)
            
            dados_para_inserir = []
            
            # 3. Decision Logic: Use Branches or Consolidated RPA
            # If all establishments have the SAME CNPJ as Matriz, it's just multi-activity for one company.
            only_matriz = all(e['cnpj'] == main_cnpj for e in estabelecimentos) if estabelecimentos else False

            if estabelecimentos and (abs(sum_est - total_rpa) < 0.05 or only_matriz):
                # Perfect match OR it's just one company with multiple activities
                # In only_matriz case, we should STILL check if it's better to use Total RPA if sum_est is different
                val_to_use = total_rpa if (only_matriz and total_rpa > 0) else sum_est
                
                if only_matriz:
                    dados_para_inserir.append({
                        'cnpj': main_cnpj, 'ano': pa_year, 'mes': pa_month,
                        'valor': val_to_use, 'origem': 'PGDAS',
                        'detalhes': json.dumps({'filename': filename, 'mode': 'matriz_consolidada_atividades'})
                    })
                else:
                    for est in estabelecimentos:
                        dados_para_inserir.append({
                            'cnpj': est['cnpj'], 'ano': pa_year, 'mes': pa_month,
                            'valor': est['valor'], 'origem': 'PGDAS',
                            'detalhes': json.dumps({'filename': filename, 'mode': 'estabelecimentos_validado'})
                        })
            elif total_rpa > 0:
                # Fallback to main CNPJ if branches don't match or aren't found
                # But if there were branches and it didn't match, we should flag it
                reason_suffix = ""
                if sum_est > 0:
                    reason_suffix = f" (Soma Filiais R$ {sum_est:.2f} != Total R$ {total_rpa:.2f})"
                
                dados_para_inserir.append({
                    'cnpj': main_cnpj, 'ano': pa_year, 'mes': pa_month,
                    'valor': total_rpa, 'origem': 'PGDAS',
                    'detalhes': json.dumps({'filename': filename, 'mode': 'consolidado_rpa_fallback', 'warning': reason_suffix})
                })
                if sum_est > 0:
                    res_dict["reason"] = f"Divergência de valores{reason_suffix}"
            
            # 4. Extract History (always useful for missing months)
            historico = extract_historico_consolidado(text_content)
            for h in historico:
                # Avoid duplicating the current PA month
                if not (h['ano'] == pa_year and h['mes'] == pa_month):
                    dados_para_inserir.append({
                        'cnpj': main_cnpj, 'ano': h['ano'], 'mes': h['mes'],
                        'valor': h['valor'], 'origem': 'PGDAS',
                        'detalhes': json.dumps({'filename': filename, 'mode': 'historico_12m'})
                    })

            if not dados_para_inserir:
                res_dict["reason"] = "Nenhum valor identificado (RPA ou Histórico)"
                return res_dict

            count = 0
            for dado in dados_para_inserir:
                # Attribute to correct company if CNPJ matches a registered branch or sub-company
                empresa_alvo_id = get_empresa_id_by_cnpj(conn, dado['cnpj']) or empresa_id
                conn.execute("""
                    INSERT INTO faturamentos (empresa_id, cnpj, ano, mes, valor, origem, detalhes_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cnpj, ano, mes, origem) DO UPDATE SET
                        valor = EXCLUDED.valor,
                        detalhes_json = EXCLUDED.detalhes_json,
                        data_importacao = CURRENT_TIMESTAMP
                """, (empresa_alvo_id, dado['cnpj'], dado['ano'], dado['mes'], dado['valor'], dado['origem'], dado['detalhes']))
                count += 1
            
            res_dict["status"] = "success"
            if res_dict["reason"] == "Unknown":
                res_dict["reason"] = f"OK ({count} reg)"
            res_dict["records"] = count
            return res_dict
    except Exception as e:
        res_dict["reason"] = f"Erro técnico: {str(e)}"
        return res_dict

def scan_folder(path):
    total_files = 0
    records_inserted = 0
    skipped_files = 0
    errors = 0
    
    # Diagnostic logging (absolute path to data folder)
    log_path = '/home/odivalmp/auditor_contabil/portatil_faturamento/data/sync_log.txt'
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    with get_db() as conn:
        with open(log_path, 'a', encoding='utf-8') as log_f:
            log_f.write(f"\n--- Sync started at {datetime.now()} ---\n")
            for root, _, files in os.walk(path):
                for file in files:
                    if file.upper().endswith(".PDF"):
                        total_files += 1
                        file_full = os.path.join(root, file)
                        try:
                            res = process_pgdas_pdf(file_full, conn)
                            log_f.write(f"File: {file} | Status: {res['status']} | Reason: {res['reason']} | Records: {res['records']}\n")
                            if res['status'] == 'success': 
                                records_inserted += res['records']
                            elif res['status'] == 'skipped':
                                skipped_files += 1
                            else:
                                errors += 1
                        except Exception as e:
                            log_f.write(f"File: {file} | technical error: {str(e)}\n")
                            print(f"[ERR] Error on {file}: {e}")
                            errors += 1
                        
    return {
        "files_found": total_files,
        "records_inserted": records_inserted,
        "skipped": skipped_files,
        "errors": errors
    }
