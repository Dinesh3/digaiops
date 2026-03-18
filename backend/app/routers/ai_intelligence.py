"""
AI/ML Intelligence Router - API endpoints for AI-powered DNS/DHCP/IPAM features
Provides endpoints for flow analysis, capacity prediction, anomaly detection, etc.
"""

from fastapi import APIRouter, HTTPException, Body
from typing import Dict, List, Optional, Any
from pydantic import BaseModel
from datetime import datetime

# Import AI/ML services
import sys
sys.path.append('..')

from app.services.dns_flow_analyzer import DNSFlowAnalyzer, DNSBlockingDetector
from app.services.dhcp_capacity_predictor import DHCPCapacityPredictor, RogueDHCPDetector
from app.services.stale_ip_detector import StaleIPDetector, IPAMOptimizer
from app.services.ai_troubleshooter import TroubleshootingAssistant, RunbookAutomation
from app.services.dns_anomaly_detector import DNSAnomalyDetector, FailurePredictor


router = APIRouter(prefix="/api/ai-intelligence", tags=["AI/ML Intelligence"])


# ==================== Request/Response Models ====================

class DNSFlowRequest(BaseModel):
    domain: str
    record_type: str = "A"
    nameserver_group: str = "root"  # Options: root, root_wf, root_wl, oc, ecmc

class DNSBlockingRequest(BaseModel):
    domain: str

class DHCPPredictionRequest(BaseModel):
    scope: str
    historical_data: List[Dict[str, Any]]

class DHCPScopeHealthRequest(BaseModel):
    scopes: List[Dict[str, Any]]

class StaleIPRequest(BaseModel):
    fixed_addresses: List[Dict[str, Any]]
    network_data: Optional[Dict[str, Any]] = None

class StaleIPReclamationRequest(BaseModel):
    stale_ips: List[Dict[str, Any]]
    grace_period_days: int = 7
    dry_run: bool = True

class IPAMOptimizationRequest(BaseModel):
    networks: List[Dict[str, Any]]

class TroubleshootingRequest(BaseModel):
    problem_description: str
    context: Optional[Dict[str, Any]] = None

class RunbookExecutionRequest(BaseModel):
    alert: Dict[str, Any]
    auto_execute: bool = False

class AnomalyDetectionRequest(BaseModel):
    current_metrics: Dict[str, Any]
    historical_metrics: List[Dict[str, Any]]

class QueryPatternRequest(BaseModel):
    query_log: List[Dict[str, Any]]

class FailurePredictionRequest(BaseModel):
    service: str
    health_metrics: List[Dict[str, Any]]


# ==================== DNS Flow Analysis Endpoints ====================

@router.post("/dns/flow-analysis")
async def analyze_dns_flow(request: DNSFlowRequest):
    """
    Trace DNS resolution path with AI analysis using OpenAI internal nameservers
    
    Analyzes complete DNS resolution flow including:
    - Local resolution check (using local nameservers - NOT public DNS)
    - Authoritative server verification
    - Delegation chain validation
    - Zone vs Record classification
    - Environment detection (Prod/SIT/UAT)
    - Blocking detection (firewall, ACL, policy)
    - AI-powered comprehensive insights and recommendations
    
    Nameserver Groups:
    - public_root: All public root servers (default)
    - internal_root_wf: internal datacenter
    - internal_root_wl: internal datacenter  

    """
    try:
        analyzer = DNSFlowAnalyzer(nameserver_group=request.nameserver_group)
        result = await analyzer.trace_resolution_path(
            domain=request.domain,
            record_type=request.record_type
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dns/blocking-analysis")
async def analyze_dns_blocking(request: DNSBlockingRequest):
    """
    Analyze if domain is blocked and why
    
    Checks for blocking at various levels:
    - DNS resolution
    - RPZ (Response Policy Zone)
    - Threat intelligence feeds
    - AI explanation of blocking reason
    """
    try:
        detector = DNSBlockingDetector()
        result = await detector.analyze_blocking(domain=request.domain)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== DHCP Capacity Prediction Endpoints ====================

@router.post("/dhcp/capacity-prediction")
async def predict_dhcp_exhaustion(request: DHCPPredictionRequest):
    """
    Predict when DHCP scope will exhaust using ML
    
    Analyzes historical lease data to predict:
    - When scope will run out of IPs
    - Current utilization trends
    - AI-generated expansion recommendations
    """
    try:
        predictor = DHCPCapacityPredictor()
        result = await predictor.predict_exhaustion(
            scope=request.scope,
            historical_data=request.historical_data
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dhcp/scope-health")
async def analyze_scope_health(request: DHCPScopeHealthRequest):
    """
    Analyze health of multiple DHCP scopes
    
    Provides health status for all DHCP scopes:
    - Current utilization
    - Status (healthy/warning/critical)
    - Overall summary
    """
    try:
        predictor = DHCPCapacityPredictor()
        result = await predictor.analyze_scope_health(scopes=request.scopes)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Stale IP Detection Endpoints ====================

@router.post("/ipam/stale-ip-detection")
async def detect_stale_ips(request: StaleIPRequest):
    """
    Identify unused/stale IP addresses for reclamation
    
    Analyzes fixed IP reservations to identify:
    - Inactive/stale IPs
    - Confidence scores for reclamation
    - AI-generated reclamation workflow
    """
    try:
        detector = StaleIPDetector()
        result = await detector.identify_stale_ips(
            fixed_addresses=request.fixed_addresses,
            network_data=request.network_data
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ipam/reclamation-workflow")
async def execute_reclamation(request: StaleIPReclamationRequest):
    """
    Execute automated IP reclamation workflow
    
    Automates IP reclamation with:
    - Grace period notifications
    - Auto-reclamation for high-confidence IPs
    - Manual approval for medium-confidence IPs
    """
    try:
        detector = StaleIPDetector()
        result = await detector.auto_reclaim_workflow(
            stale_ips=request.stale_ips,
            grace_period_days=request.grace_period_days,
            dry_run=request.dry_run
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ipam/optimization-analysis")
async def analyze_ipam_optimization(request: IPAMOptimizationRequest):
    """
    Analyze IP allocation for optimization opportunities
    
    Identifies:
    - Over-allocated subnets (waste)
    - Under-provisioned subnets (risk)
    - Consolidation opportunities
    - AI-powered optimization strategy
    """
    try:
        optimizer = IPAMOptimizer()
        result = await optimizer.analyze_subnet_allocation(networks=request.networks)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AI Troubleshooting Endpoints ====================

@router.post("/troubleshooting/start-session")
async def start_troubleshooting(request: TroubleshootingRequest):
    """
    Start AI-guided troubleshooting session
    
    Provides step-by-step troubleshooting with:
    - Automated diagnostic checks
    - AI-guided next steps
    - Root cause analysis
    - Fix recommendations
    """
    try:
        assistant = TroubleshootingAssistant()
        result = await assistant.start_troubleshooting_session(
            problem_description=request.problem_description,
            context=request.context
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/troubleshooting/runbook-execution")
async def execute_runbook(request: RunbookExecutionRequest):
    """
    AI-powered runbook selection and execution
    
    Automatically:
    - Selects appropriate runbook for the issue
    - Executes low-risk runbooks automatically
    - Requests approval for high-risk operations
    """
    try:
        automation = RunbookAutomation()
        result = await automation.select_and_execute_runbook(
            alert=request.alert,
            auto_execute=request.auto_execute
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Anomaly Detection Endpoints ====================

@router.post("/anomaly/dns-detection")
async def detect_dns_anomalies(request: AnomalyDetectionRequest):
    """
    ML-based DNS anomaly detection
    
    Detects unusual patterns in:
    - Query volume
    - Error rates
    - Response times
    - NXDOMAIN rates
    - AI analysis of detected anomalies
    """
    try:
        detector = DNSAnomalyDetector()
        result = await detector.detect_dns_anomalies(
            current_metrics=request.current_metrics,
            historical_metrics=request.historical_metrics
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/anomaly/query-patterns")
async def analyze_query_patterns(request: QueryPatternRequest):
    """
    Analyze DNS query patterns for suspicious activity
    
    Detects:
    - DNS tunneling attempts
    - Query floods
    - High NXDOMAIN rates
    - Security threats
    - AI-powered threat assessment
    """
    try:
        detector = DNSAnomalyDetector()
        result = await detector.analyze_query_patterns(query_log=request.query_log)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Failure Prediction Endpoints ====================

@router.post("/prediction/service-failure")
async def predict_service_failure(request: FailurePredictionRequest):
    """
    Predict infrastructure failures before they occur
    
    Analyzes health trends to predict:
    - Failure probability
    - Estimated time to failure
    - Root cause prediction
    - Preventive action plan
    """
    try:
        predictor = FailurePredictor()
        result = await predictor.predict_service_failure(
            service=request.service,
            health_metrics=request.health_metrics
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Health Check Endpoint ====================

@router.get("/health")
async def health_check():
    """Check if AI/ML services are operational"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "dns_flow_analyzer": "operational",
            "dhcp_predictor": "operational",
            "stale_ip_detector": "operational",
            "ai_troubleshooter": "operational",
            "anomaly_detector": "operational"
        }
    }


# ==================== Feature Info Endpoint ====================

@router.get("/features")
async def get_features():
    """List available AI/ML features"""
    return {
        "features": [
            {
                "category": "DNS Intelligence",
                "features": [
                    "DNS Flow Analysis - Trace complete resolution path",
                    "Blocking Detection - Identify why domains are blocked",
                    "Anomaly Detection - ML-based unusual pattern detection"
                ]
            },
            {
                "category": "DHCP Intelligence",
                "features": [
                    "Capacity Prediction - ML-based exhaustion forecasting",
                    "Scope Health Analysis - Multi-scope health monitoring",
                    "Rogue DHCP Detection - Unauthorized server detection"
                ]
            },
            {
                "category": "IPAM Intelligence",
                "features": [
                    "Stale IP Detection - Identify reclaimable IPs",
                    "Auto-Reclamation - Automated IP cleanup workflow",
                    "Optimization Analysis - Subnet efficiency analysis"
                ]
            },
            {
                "category": "AI Troubleshooting",
                "features": [
                    "Guided Troubleshooting - Step-by-step AI assistance",
                    "Runbook Automation - Intelligent runbook execution",
                    "Root Cause Analysis - AI-powered diagnostics"
                ]
            },
            {
                "category": "Predictive Analytics",
                "features": [
                    "Failure Prediction - Predict issues before they occur",
                    "Query Pattern Analysis - Security threat detection",
                    "Trend Analysis - Resource utilization forecasting"
                ]
            }
        ]
    }
