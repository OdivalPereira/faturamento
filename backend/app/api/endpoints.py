from ..database.db import get_db
from ..parsing.pgdas import scan_folder
import os
import re
import ctypes
from ctypes import wintypes
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class FolderSyncSchema(BaseModel):
    path: str

@router.get("/empresas")
async def list_empresas():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM empresas ORDER BY razao_social").fetchall()
        return {"status": "success", "data": [dict(row) for row in rows]}

@router.get("/contadores")
async def list_contadores():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM contadores").fetchall()
        return {"status": "success", "data": [dict(row) for row in rows]}

@router.get("/empresas/{empresa_id}/socios/ativos")
async def list_socios_ativos(empresa_id: int):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, nome, cpf, percentual 
            FROM socios 
            WHERE empresa_id = ? 
            AND (data_saida IS NULL OR data_saida > DATE('now'))
            ORDER BY nome
        """, (empresa_id,)).fetchall()
        
        socios = []
        for row in rows:
            d = dict(row)
            d['cargo'] = "Sócio Administrador" if (d['percentual'] or 0) >= 50 else "Sócio"
            socios.append(d)
            
        if not socios:
            res_legal = conn.execute("SELECT responsavel_legal FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
            if res_legal and res_legal['responsavel_legal']:
                socios.append({"id": -1, "nome": res_legal['responsavel_legal'], "cpf": "", "percentual": 100.0, "cargo": "Responsável Legal"})
        
        return {"status": "success", "data": socios}

@router.get("/empresas/{empresa_id}/cnpjs")
async def list_cnpjs(empresa_id: int):
    with get_db() as conn:
        emp = conn.execute("SELECT cnpj_cpf FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
        if not emp: return {"status": "success", "data": []}
        
        root = re.sub(r'\D', '', emp['cnpj_cpf'])[:8]
        rows = conn.execute("""
            SELECT DISTINCT cnpj FROM faturamentos 
            WHERE REPLACE(REPLACE(REPLACE(cnpj, '.', ''), '/', ''), '-', '') LIKE ?
            ORDER BY cnpj
        """, (f"{root}%",)).fetchall()
        
        return {"status": "success", "data": [{"cnpj": r['cnpj'], "label": f"CNPJ: {r['cnpj']}"} for r in rows]}

@router.get("/empresas/{empresa_id}/faturamentos")
async def list_faturamentos(empresa_id: int):
    with get_db() as conn:
        emp = conn.execute("SELECT cnpj_cpf FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
        if not emp: return {"status": "success", "data": []}
        
        root = re.sub(r'\D', '', emp['cnpj_cpf'])[:8]
        rows = conn.execute("""
            SELECT * FROM faturamentos 
            WHERE REPLACE(REPLACE(REPLACE(cnpj, '.', ''), '/', ''), '-', '') LIKE ?
            ORDER BY ano DESC, mes DESC
        """, (f"{root}%",)).fetchall()
        
        return {"status": "success", "data": [dict(r) for r in rows]}

@router.post("/empresas/faturamentos/sync-folder")
async def sync_folder(payload: FolderSyncSchema):
    if not os.path.exists(payload.path):
        raise HTTPException(status_code=400, detail="Caminho não encontrado.")
    
    report = scan_folder(payload.path)
    msg = f"Sincronização concluída. {report['records_inserted']} registros processados em {report['files_found']} arquivos."
    if report['errors'] > 0:
        msg += f" ({report['errors']} erros encontrados)"
    return {"status": "success", "message": msg, "report": report}

@router.get("/utils/select-folder")
def select_folder():
    if os.name != 'nt':
        return {"status": "success", "data": {"path": ""}}
        
    try:
        # Define structures for Windows API
        class BROWSEINFO(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wintypes.HWND),
                ("pidlRoot", wintypes.LPVOID),
                ("pszDisplayName", wintypes.LPWSTR),
                ("lpszTitle", wintypes.LPWSTR),
                ("ulFlags", wintypes.UINT),
                ("lpfn", wintypes.LPVOID),
                ("lParam", wintypes.LPARAM),
                ("iImage", ctypes.c_int),
            ]

        # Windows constants
        BIF_RETURNONLYFSDIRS = 0x0001
        BIF_NEWDIALOGSTYLE = 0x0040
        MAX_PATH = 260

        # Initialize
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        
        # COM must be initialized for SHBrowseForFolder
        ole32.CoInitialize(None)
        
        bi = BROWSEINFO()
        bi.hwndOwner = None
        bi.lpszTitle = "Selecione a pasta com os PDFs do PGDAS"
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
        
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        
        if pidl:
            path_buf = ctypes.create_unicode_buffer(MAX_PATH)
            if shell32.SHGetPathFromIDListW(pidl, path_buf):
                # Free PIDL with Shell Task Allocator
                try:
                    ctypes.windll.shell32.ILFree(pidl)
                except AttributeError:
                    # Fallback for older systems or if ILFree not exposed directly
                    pass
                
                path = path_buf.value
                ole32.CoUninitialize()
                return {"status": "success", "data": {"path": path}}
        
        ole32.CoUninitialize()
        return {"status": "success", "data": {"path": ""}}
    except Exception as e:
        print(f"[ERR] Error in SHBrowseForFolder: {e}")
        return {"status": "success", "data": {"path": ""}}
