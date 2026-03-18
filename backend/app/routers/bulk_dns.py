"""
Bulk DNS Management Router
Handles CSV uploads, YAML exports, and bulk DNS operations
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Query, Depends
from fastapi.responses import PlainTextResponse, StreamingResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from datetime import datetime
import io

from app.services.bulk_dns_service import BulkDNSService, BulkDNSRecord
from app.config.database import get_db
from app.models.database_models import BulkDNSRecord as DBBulkDNSRecord

router = APIRouter()


@router.get("/bulk/records")
def get_bulk_records(
    ticket_no: Optional[str] = None,
    jira_ticket: Optional[str] = None,
    action: Optional[str] = None,
    record_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    Get bulk DNS records with filtering and pagination
    
    Query Parameters:
    - ticket_no: Filter by change ticket number
    - jira_ticket: Filter by Jira ticket number
    - action: Filter by action type (create, import, modify, delete)
    - record_type: Filter by DNS record type (A, CNAME, MX, etc.)
    - search: Search in FQDN, PTR, or comment
    - page: Page number (default: 1)
    - page_size: Records per page (default: 50, max: 500)
    """
    # Build query
    query = db.query(DBBulkDNSRecord)
    
    # Apply filters
    if ticket_no:
        query = query.filter(DBBulkDNSRecord.ticket_no == ticket_no)
    
    if jira_ticket:
        query = query.filter(DBBulkDNSRecord.jira_ticket == jira_ticket)
    
    if action:
        query = query.filter(DBBulkDNSRecord.action == action)
    
    if record_type:
        query = query.filter(DBBulkDNSRecord.type == record_type)
    
    # Search filter
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                DBBulkDNSRecord.fqdn.ilike(search_pattern),
                DBBulkDNSRecord.ptrdname.ilike(search_pattern),
                DBBulkDNSRecord.comment.ilike(search_pattern),
                DBBulkDNSRecord.jira_ticket.ilike(search_pattern),
                DBBulkDNSRecord.ticket_no.ilike(search_pattern)
            )
        )
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    records = query.order_by(DBBulkDNSRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    # Convert to Pydantic models
    pydantic_records = [BulkDNSRecord.model_validate(r) for r in records]
    
    return {
        "records": pydantic_records,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.post("/bulk/upload-csv")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload CSV file and convert to DNS records
    
    Expected CSV columns:
    ticket_no,fqdn,ptrdname,action,type,comment,ip_addr,canonical,text,
    preference,mail_exchanger,priority,weight,port,target,ttl,exemptions,
    identifier,mod_ip_addr,mod_canonical,mod_text,mod_preference,
    mod_mail_exchanger,mod_priority,mod_weight,mod_port,mod_target,mod_ttl
    """
    try:
        # Read CSV content
        contents = await file.read()
        
        # Try different encodings
        try:
            csv_text = contents.decode('utf-8')
        except UnicodeDecodeError:
            try:
                csv_text = contents.decode('utf-8-sig')  # Handle BOM
            except UnicodeDecodeError:
                csv_text = contents.decode('latin-1')  # Fallback
        
        # Parse CSV to records
        new_records = BulkDNSService.parse_csv_to_records(csv_text)
        
        if not new_records:
            raise HTTPException(
                status_code=400, 
                detail="No valid records found in CSV. Please ensure your CSV has the correct format with required fields: ci_number (or ticket_no), action, type, and comment. Remove any comment lines starting with '#'."
            )
        
        # Add to database
        db_records = []
        for record in new_records:
            db_record = DBBulkDNSRecord(
                ticket_no=record.ticket_no,
                fqdn=record.fqdn,
                ptrdname=record.ptrdname,
                action=record.action,
                type=record.type,
                ip_addr=str(record.ip_addr) if record.ip_addr else None,
                canonical=record.canonical,
                text=record.text,
                preference=record.preference,
                mail_exchanger=record.mail_exchanger,
                priority=record.priority,
                weight=record.weight,
                port=record.port,
                target=record.target,
                ttl=record.ttl,
                exemptions=record.exemptions,
                comment=record.comment,
                jira_ticket=record.jira_ticket,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db_records.append(db_record)
        
        db.add_all(db_records)
        db.commit()
        
        # Group by ticket for summary
        tickets = {}
        for record in new_records:
            ticket_key = record.ticket_no
            if ticket_key not in tickets:
                tickets[ticket_key] = {"total": 0, "types": set(), "actions": set()}
            tickets[ticket_key]["total"] += 1
            tickets[ticket_key]["types"].add(record.type)
            tickets[ticket_key]["actions"].add(record.action)
        
        summary = []
        for ticket, info in tickets.items():
            summary.append({
                "ticket_no": ticket,
                "total_records": info["total"],
                "record_types": list(info["types"]),
                "actions": list(info["actions"])
            })
        
        return {
            "success": True,
            "message": f"Successfully uploaded {len(new_records)} records",
            "total_records": len(new_records),
            "tickets": summary,
            "records": new_records
        }
    
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid file encoding. Please upload UTF-8 encoded CSV")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing CSV: {str(e)}")


@router.post("/bulk/records")
def create_bulk_record(record: BulkDNSRecord, db: Session = Depends(get_db)):
    """Create a single bulk DNS record"""
    # Extract Jira ticket if not already set
    if not record.jira_ticket and record.comment:
        record.jira_ticket = BulkDNSService.extract_jira_ticket(record.comment)
    
    # Create database record
    db_record = DBBulkDNSRecord(
        ticket_no=record.ticket_no,
        fqdn=record.fqdn,
        ptrdname=record.ptrdname,
        action=record.action,
        type=record.type,
        ip_addr=str(record.ip_addr) if record.ip_addr else None,
        canonical=record.canonical,
        text=record.text,
        preference=record.preference,
        mail_exchanger=record.mail_exchanger,
        priority=record.priority,
        weight=record.weight,
        port=record.port,
        target=record.target,
        ttl=record.ttl,
        exemptions=record.exemptions,
        comment=record.comment,
        jira_ticket=record.jira_ticket,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    
    return {"success": True, "record": BulkDNSRecord.model_validate(db_record)}


@router.put("/bulk/records/{record_id}")
def update_bulk_record(record_id: int, record: BulkDNSRecord, db: Session = Depends(get_db)):
    """Update a bulk DNS record"""
    db_record = db.query(DBBulkDNSRecord).filter(DBBulkDNSRecord.id == record_id).first()
    
    if not db_record:
        raise HTTPException(status_code=404, detail="Record not found")
    
    # Update fields
    db_record.ticket_no = record.ticket_no
    db_record.fqdn = record.fqdn
    db_record.ptrdname = record.ptrdname 
    db_record.action = record.action
    db_record.type = record.type
    db_record.ip_addr = str(record.ip_addr) if record.ip_addr else None
    db_record.canonical = record.canonical
    db_record.text = record.text
    db_record.preference = record.preference
    db_record.mail_exchanger = record.mail_exchanger
    db_record.priority = record.priority
    db_record.weight = record.weight
    db_record.port = record.port
    db_record.target = record.target
    db_record.ttl = record.ttl
    db_record.exemptions = record.exemptions
    db_record.comment = record.comment
    db_record.jira_ticket = record.jira_ticket
    db_record.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_record)
    
    return {"success": True, "record": BulkDNSRecord.model_validate(db_record)}


@router.delete("/bulk/records/{record_id}")
def delete_bulk_record(record_id: int, db: Session = Depends(get_db)):
    """Delete a bulk DNS record"""
    db_record = db.query(DBBulkDNSRecord).filter(DBBulkDNSRecord.id == record_id).first()
    
    if not db_record:
        raise HTTPException(status_code=404, detail="Record not found")
    
    db.delete(db_record)
    db.commit()
    
    return {"success": True, "deleted": True}


@router.delete("/bulk/records")
def delete_bulk_records(record_ids: List[int], db: Session = Depends(get_db)):
    """Delete multiple bulk DNS records"""
    deleted_count = db.query(DBBulkDNSRecord).filter(DBBulkDNSRecord.id.in_(record_ids)).delete(synchronize_session=False)
    db.commit()
    
    remaining_count = db.query(DBBulkDNSRecord).count()
    
    return {
        "success": True,
        "deleted_count": deleted_count,
        "remaining_count": remaining_count
    }


@router.delete("/bulk/clear-all")
def clear_all_bulk_records(confirm: bool = Query(False), db: Session = Depends(get_db)):
    """Clear all bulk DNS records (requires confirmation)"""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Please confirm deletion by setting confirm=true"
        )
    
    record_count = db.query(DBBulkDNSRecord).count()
    db.query(DBBulkDNSRecord).delete()
    db.commit()
    
    return {
        "success": True,
        "message": f"Cleared {record_count} records"
    }


@router.get("/bulk/export/yaml", response_class=PlainTextResponse)
def export_to_yaml(ticket_no: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Export DNS records to YAML format
    
    Query Parameters:
    - ticket_no: Filter by specific ticket number (exports all if not provided)
    """
    # Get records from database
    query = db.query(DBBulkDNSRecord)
    if ticket_no:
        query = query.filter(DBBulkDNSRecord.ticket_no == ticket_no)
    
    db_records = query.all()
    pydantic_records = [BulkDNSRecord.model_validate(r) for r in db_records]
    
    yaml_content = BulkDNSService.convert_to_yaml(pydantic_records, ticket_no)
    
    return yaml_content


@router.get("/bulk/view/yaml", response_class=HTMLResponse)
def view_yaml_in_browser(ticket_no: Optional[str] = None, db: Session = Depends(get_db)):
    """
    View DNS records as YAML in browser with copy functionality
    
    Query Parameters:
    - ticket_no: Filter by specific ticket number (shows all if not provided)
    """
    # Get records from database
    query = db.query(DBBulkDNSRecord)
    if ticket_no:
        query = query.filter(DBBulkDNSRecord.ticket_no == ticket_no)
    
    db_records = query.all()
    pydantic_records = [BulkDNSRecord.model_validate(r) for r in db_records]
    
    yaml_content = BulkDNSService.convert_to_yaml(pydantic_records, ticket_no)
    
    # Escape the YAML content for HTML
    import html
    yaml_content_escaped = html.escape(yaml_content)
    
    ticket_label = f"CI Number: {ticket_no}" if ticket_no else "All Records"
    download_filename = f"{ticket_no}_" if ticket_no else ""
    download_filename += f"dns_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
    
    # HTML template with YAML viewer and copy button
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DNS Records YAML - {ticket_no or 'All Records'}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{
            font-size: 28px;
            font-weight: 600;
        }}
        .header .ticket {{
            background: rgba(255, 255, 255, 0.2);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
        }}
        .actions {{
            padding: 20px 30px;
            background: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        .btn {{
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }}
        .btn-primary {{
            background: #667eea;
            color: white;
        }}
        .btn-primary:hover {{
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }}
        .btn-secondary {{
            background: #6c757d;
            color: white;
        }}
        .btn-secondary:hover {{
            background: #5a6268;
        }}
        .yaml-container {{
            padding: 30px;
            position: relative;
        }}
        pre {{
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 20px;
            overflow-x: auto;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace;
            font-size: 13px;
            line-height: 1.6;
            color: #212529;
            position: relative;
        }}
        .copy-notification {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: #28a745;
            color: white;
            padding: 15px 25px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            display: none;
            align-items: center;
            gap: 10px;
            z-index: 1000;
            animation: slideIn 0.3s ease;
        }}
        @keyframes slideIn {{
            from {{
                transform: translateX(400px);
                opacity: 0;
            }}
            to {{
                transform: translateX(0);
                opacity: 1;
            }}
        }}
        .copy-notification.show {{
            display: flex;
        }}
        .stats {{
            display: flex;
            gap: 20px;
            margin-left: auto;
            font-size: 14px;
            color: #6c757d;
        }}
        .stat {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .stat strong {{
            color: #495057;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📄 DNS Records YAML</h1>
            <div class="ticket">{ticket_label}</div>
        </div>
        
        <div class="actions">
            <button class="btn btn-primary" onclick="copyToClipboard()">
                📋 Copy to Clipboard
            </button>
            <button class="btn btn-secondary" onclick="downloadYAML()">
                💾 Download YAML
            </button>
            <div class="stats">
                <div class="stat">
                    <strong>Lines:</strong> <span id="lineCount"></span>
                </div>
                <div class="stat">
                    <strong>Size:</strong> <span id="sizeInfo"></span>
                </div>
            </div>
        </div>
        
        <div class="yaml-container">
            <pre id="yamlContent">{yaml_content_escaped}</pre>
        </div>
    </div>
    
    <div class="copy-notification" id="notification">
        ✓ Copied to clipboard!
    </div>
    
    <script>
        // Calculate stats
        const yamlContent = document.getElementById('yamlContent').textContent;
        const lines = yamlContent.split('\\n').length;
        const sizeBytes = new Blob([yamlContent]).size;
        const sizeKB = (sizeBytes / 1024).toFixed(2);
        
        document.getElementById('lineCount').textContent = lines;
        document.getElementById('sizeInfo').textContent = sizeKB + ' KB';
        
        function copyToClipboard() {{
            const content = document.getElementById('yamlContent').textContent;
            
            navigator.clipboard.writeText(content).then(() => {{
                showNotification();
            }}).catch(err => {{
                const textArea = document.createElement('textarea');
                textArea.value = content;
                textArea.style.position = 'fixed';
                textArea.style.left = '-999999px';
                document.body.appendChild(textArea);
                textArea.select();
                try {{
                    document.execCommand('copy');
                    showNotification();
                }} catch (err) {{
                    alert('Copy failed. Please copy manually.');
                }}
                document.body.removeChild(textArea);
            }});
        }}
        
        function showNotification() {{
            const notification = document.getElementById('notification');
            notification.classList.add('show');
            setTimeout(() => {{
                notification.classList.remove('show');
            }}, 2000);
        }}
        
        function downloadYAML() {{
            const content = document.getElementById('yamlContent').textContent;
            const blob = new Blob([content], {{ type: 'application/x-yaml' }});
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = '{download_filename}';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }}
    </script>
</body>
</html>"""
    
    return html_content


@router.get("/bulk/download/yaml")
def download_yaml(ticket_no: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Download DNS records as YAML file
    
    Query Parameters:
    - ticket_no: Filter by specific ticket number (downloads all if not provided)
    """
    # Get records from database
    query = db.query(DBBulkDNSRecord)
    if ticket_no:
        query = query.filter(DBBulkDNSRecord.ticket_no == ticket_no)
    
    db_records = query.all()
    pydantic_records = [BulkDNSRecord.model_validate(r) for r in db_records]
    
    yaml_content = BulkDNSService.convert_to_yaml(pydantic_records, ticket_no)
    
    # Generate filename
    if ticket_no:
        filename = f"{ticket_no}_dns_records.yaml"
    else:
        filename = f"dns_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
    
    # Create streaming response
    return StreamingResponse(
        io.BytesIO(yaml_content.encode('utf-8')),
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.get("/bulk/download/csv-template", response_class=PlainTextResponse)
def download_csv_template():
    """Download CSV template with headers and examples"""
    template = BulkDNSService.generate_csv_template()
    return template


@router.get("/bulk/statistics")
def get_bulk_statistics(db: Session = Depends(get_db)):
    """Get statistics about bulk DNS records"""
    total_records = db.query(DBBulkDNSRecord).count()
    
    if total_records == 0:
        return {
            "total_records": 0,
            "by_ticket": {},
            "by_action": {},
            "by_type": {},
            "recent_records": []
        }
    
    # Count by ticket
    from sqlalchemy import func
    by_ticket_query = db.query(
        DBBulkDNSRecord.ticket_no,
        func.count(DBBulkDNSRecord.id).label('count')
    ).group_by(DBBulkDNSRecord.ticket_no).all()
    by_ticket = {item.ticket_no: item.count for item in by_ticket_query}
    
    # Count by action
    by_action_query = db.query(
        DBBulkDNSRecord.action,
        func.count(DBBulkDNSRecord.id).label('count')
    ).group_by(DBBulkDNSRecord.action).all()
    by_action = {item.action: item.count for item in by_action_query}
    
    # Count by type
    by_type_query = db.query(
        DBBulkDNSRecord.type,
        func.count(DBBulkDNSRecord.id).label('count')
    ).group_by(DBBulkDNSRecord.type).all()
    by_type = {item.type: item.count for item in by_type_query}
    
    # Get recent records (last 10)
    recent_db_records = db.query(DBBulkDNSRecord).order_by(DBBulkDNSRecord.created_at.desc()).limit(10).all()
    recent_records = [BulkDNSRecord.model_validate(r) for r in recent_db_records]
    
    return {
        "total_records": total_records,
        "by_ticket": by_ticket,
        "by_action": by_action,
        "by_type": by_type,
        "tickets_count": len(by_ticket),
        "recent_records": recent_records
    }


@router.post("/bulk/validate")
def validate_records(records: List[BulkDNSRecord]):
    """
    Validate DNS records before saving
    Returns validation errors if any
    """
    errors = []
    
    for idx, record in enumerate(records):
        record_errors = []
        
        # Validate FQDN or PTR
        if not record.fqdn and not record.ptrdname:
            record_errors.append("Either fqdn or ptrdname must be provided")
        
        # Validate action
        if record.action not in ['create', 'import', 'modify', 'delete']:
            record_errors.append(f"Invalid action: {record.action}")
        
        # Validate type
        valid_types = ['A', 'AAAA', 'CNAME', 'MX', 'PTR', 'SRV', 'TXT', 'NS', 'SOA']
        if record.type not in valid_types:
            record_errors.append(f"Invalid type: {record.type}. Must be one of {valid_types}")
        
        # Type-specific validation
        if record.type == 'A' and record.action == 'create' and not record.ip_addr:
            record_errors.append("A records require ip_addr")
        
        if record.type == 'CNAME' and record.action == 'create' and not record.canonical:
            record_errors.append("CNAME records require canonical")
        
        if record.type == 'MX' and record.action == 'create':
            if not record.mail_exchanger:
                record_errors.append("MX records require mail_exchanger")
            if record.preference is None:
                record_errors.append("MX records require preference")
        
        if record.type == 'SRV' and record.action == 'create':
            if not all([record.priority is not None, record.weight is not None, 
                       record.port is not None, record.target]):
                record_errors.append("SRV records require priority, weight, port, and target")
        
        if record.type == 'PTR' and record.action == 'create' and not record.ptrdname:
            record_errors.append("PTR records require ptrdname")
        
        # Import/Modify validation
        if record.action in ['import', 'modify'] and not record.identifier:
            record_errors.append(f"{record.action} action requires identifier")
        
        if record_errors:
            errors.append({
                "record_index": idx,
                "fqdn": record.fqdn,
                "ptrdname": record.ptrdname,
                "errors": record_errors
            })
    
    if errors:
        return {
            "valid": False,
            "error_count": len(errors),
            "errors": errors
        }
    
    return {
        "valid": True,
        "message": f"All {len(records)} records are valid"
    }
