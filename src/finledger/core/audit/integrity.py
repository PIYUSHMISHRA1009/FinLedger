"""
FinLedger Audit Log Immutability Proofs

Cryptographic integrity verification for audit logs using:
- Hash chaining (Merkle tree)
- Tamper evidence
- Verification endpoint
- Proof generation
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from collections import defaultdict
import hashlib
import json

from sqlalchemy import select, func, and_, or_, desc, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

from finledger.db.models import AuditLog, User
from finledger.db.database import Base
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB


# =============================================================================
# ENUMS & DATA CLASSES
# =============================================================================

class ProofType(str, Enum):
    MERKLE_ROOT = "MERKLE_ROOT"
    HASH_CHAIN = "HASH_CHAIN"
    INCLUSION = "INCLUSION"
    CONSISTENCY = "CONSISTENCY"


class VerificationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    TAMPERED = "TAMPERED"
    INCOMPLETE = "INCOMPLETE"


@dataclass
class AuditLogEntry:
    """Individual audit log entry with hash."""
    id: UUID
    action: str
    resource_type: str
    resource_id: Optional[UUID]
    old_values: Optional[Dict[str, Any]]
    new_values: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    user_agent: Optional[str]
    request_id: Optional[str]
    created_at: datetime
    user_id: Optional[UUID]
    
    # Computed fields
    entry_hash: Optional[str] = None
    chain_hash: Optional[str] = None
    sequence: int = 0


@dataclass
class MerkleProof:
    """Merkle tree inclusion proof."""
    leaf_hash: str
    leaf_index: int
    root_hash: str
    siblings: List[Dict[str, str]]  # [{"position": "left/right", "hash": "..."}]
    tree_height: int


@dataclass
class ChainProof:
    """Hash chain proof."""
    start_hash: str
    end_hash: str
    chain_length: int
    hashes: List[str]


@dataclass
class VerificationResult:
    """Result of integrity verification."""
    status: VerificationStatus
    proof_type: ProofType
    verified_count: int
    total_count: int
    tampered_entries: List[Dict[str, Any]] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AuditIntegrityReport:
    """Complete integrity report."""
    report_id: UUID
    period_start: datetime
    period_end: datetime
    total_entries: int
    verified_count: int
    tampered_count: int
    missing_count: int
    merkle_root: str
    chain_head: str
    verification_results: List[VerificationResult]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# DATABASE MODELS
# =============================================================================

from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship
from finledger.db.database import Base
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric, UniqueConstraint

class AuditLogIntegrity(Base):
    """Integrity metadata for audit logs."""
    __tablename__ = "audit_log_integrity"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    audit_log_id = Column(PG_UUID(as_uuid=True), ForeignKey("audit_logs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    
    # Hashes
    entry_hash = Column(String(64), nullable=False)  # SHA256 of entry content
    chain_hash = Column(String(64), nullable=False)  # Hash of (previous_chain_hash + entry_hash)
    merkle_leaf_hash = Column(String(64), nullable=True)  # For Merkle tree
    
    # Sequence
    sequence = Column(Integer, nullable=False, unique=True, index=True)
    
    # Merkle tree metadata
    merkle_tree_height = Column(Integer, nullable=True)
    merkle_leaf_index = Column(Integer, nullable=True)
    
    # Verification metadata
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    verification_status = Column(String(20), nullable=True)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    
    __table_args__ = (
        Index("idx_audit_integrity_sequence", "sequence"),
        Index("idx_audit_integrity_audit_log", "audit_log_id"),
    )


class MerkleTreeSnapshot(Base):
    """Merkle tree snapshots for consistency proofs."""
    __tablename__ = "merkle_tree_snapshots"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    root_hash = Column(String(64), nullable=False)
    tree_height = Column(Integer, nullable=False)
    leaf_count = Column(Integer, nullable=False)
    
    # Leaves
    leaf_hashes = Column(JSONB, nullable=False)  # Ordered list of leaf hashes
    
    # Period
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    __table_args__ = (
        Index("idx_merkle_snapshot_period", "period_start", "period_end"),
    )


class IntegrityVerificationLog(Base):
    """Log of integrity verification runs."""
    __tablename__ = "integrity_verification_logs"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    verification_type = Column(String(20), nullable=False)  # "full", "incremental", "inclusion"
    status = Column(String(20), nullable=False)  # VALID, INVALID, TAMPERED
    
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    
    total_entries = Column(Integer, default=0)
    verified_count = Column(Integer, default=0)
    tampered_count = Column(Integer, default=0)
    missing_count = Column(Integer, default=0)
    
    merkle_root = Column(String(64), nullable=True)
    chain_head = Column(String(64), nullable=True)
    
    tampered_entries = Column(JSONB, nullable=True, default=list)  # List of tampered entry IDs
    
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    initiated_by = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    __table_args__ = (
        Index("idx_integrity_log_period", "period_start", "period_end"),
        Index("idx_integrity_log_status", "status"),
    )


# =============================================================================
# AUDIT INTEGRITY SERVICE
# =============================================================================

class AuditIntegrityService:
    """
    Service for maintaining and verifying audit log integrity using:
    - Hash chaining (each entry linked to previous)
    - Merkle trees for efficient inclusion proofs
    - Periodic snapshots for consistency proofs
    - Tamper detection and alerting
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # -------------------------------------------------------------------------
    # HASH COMPUTATION
    # -------------------------------------------------------------------------
    
    def _compute_entry_hash(self, entry: AuditLog) -> str:
        """Compute SHA256 hash of audit log entry content."""
        content = {
            "id": str(entry.id),
            "action": entry.action,
            "resource_type": entry.resource_type,
            "resource_id": str(entry.resource_id) if entry.resource_id else None,
            "old_values": entry.old_values,
            "new_values": entry.new_values,
            "ip_address": entry.ip_address,
            "user_agent": entry.user_agent,
            "request_id": entry.request_id,
            "created_at": entry.created_at.isoformat(),
            "user_id": str(entry.user_id) if entry.user_id else None,
        }
        content_json = json.dumps(content, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(content_json.encode()).hexdigest()
    
    def _compute_chain_hash(self, prev_chain_hash: str, entry_hash: str) -> str:
        """Compute chain hash linking previous entry to current."""
        combined = f"{prev_chain_hash}:{entry_hash}"
        return hashlib.sha256(combined.encode()).hexdigest()
    
    def _compute_merkle_leaf_hash(self, entry_hash: str, sequence: int) -> str:
        """Compute Merkle leaf hash (includes sequence for ordering)."""
        combined = f"{sequence}:{entry_hash}"
        return hashlib.sha256(combined.encode()).hexdigest()
    
    # -------------------------------------------------------------------------
    # INTEGRITY MAINTENANCE
    # -------------------------------------------------------------------------
    
    async def compute_integrity_for_entry(self, entry: AuditLog) -> AuditLogIntegrity:
        """Compute and store integrity metadata for a new audit log entry."""
        # Get previous entry's chain hash
        prev_result = await self.db.execute(
            select(AuditLogIntegrity)
            .order_by(desc(AuditLogIntegrity.sequence))
            .limit(1)
        )
        prev_integrity = prev_result.scalar_one_or_none()
        
        prev_chain_hash = prev_integrity.chain_hash if prev_integrity else "0" * 64
        prev_sequence = prev_integrity.sequence if prev_integrity else 0
        
        # Compute hashes
        entry_hash = self._compute_entry_hash(entry)
        chain_hash = self._compute_chain_hash(prev_chain_hash, entry_hash)
        merkle_leaf_hash = self._compute_merkle_leaf_hash(entry_hash, prev_sequence + 1)
        
        # Create integrity record
        integrity = AuditLogIntegrity(
            audit_log_id=entry.id,
            entry_hash=entry_hash,
            chain_hash=chain_hash,
            merkle_leaf_hash=merkle_leaf_hash,
            sequence=prev_sequence + 1,
            merkle_tree_height=0,  # Will be updated during snapshot
            merkle_leaf_index=prev_sequence,
            verification_status=VerificationStatus.VALID.value,
        )
        
        self.db.add(integrity)
        await self.db.flush()
        return integrity
    
    async def backfill_integrity(self, batch_size: int = 1000) -> int:
        """Backfill integrity metadata for existing audit logs."""
        # Get entries without integrity records
        result = await self.db.execute(
            select(AuditLog)
            .where(~AuditLog.id.in_(
                select(AuditLogIntegrity.audit_log_id)
            ))
            .order_by(AuditLog.created_at)
            .limit(batch_size)
        )
        entries = result.scalars().all()
        
        count = 0
        for entry in entries:
            await self.compute_integrity_for_entry(entry)
            count += 1
        
        await self.db.commit()
        return count
    
    # -------------------------------------------------------------------------
    # MERKLE TREE OPERATIONS
    # -------------------------------------------------------------------------
    
    def _build_merkle_tree(self, leaf_hashes: List[str]) -> Dict[str, Any]:
        """Build Merkle tree from leaf hashes."""
        if not leaf_hashes:
            return {"root": "0" * 64, "height": 0, "leaves": []}
        
        # Pad to power of 2
        n = len(leaf_hashes)
        next_pow2 = 1
        while next_pow2 < n:
            next_pow2 *= 2
        
        padded_hashes = leaf_hashes + ["0" * 64] * (next_pow2 - n)
        
        # Build tree bottom-up
        current_level = padded_hashes
        tree_levels = [current_level]
        
        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                right = current_level[i + 1] if i + 1 < len(current_level) else "0" * 64
                combined = f"{left}:{right}"
                parent_hash = hashlib.sha256(combined.encode()).hexdigest()
                next_level.append(parent_hash)
            
            tree_levels.append(next_level)
            current_level = next_level
        
        root_hash = tree_levels[-1][0] if tree_levels[-1] else "0" * 64
        height = len(tree_levels) - 1
        
        return {
            "root": root_hash,
            "height": height,
            "levels": tree_levels,
            "leaves": leaf_hashes,
        }
    
    async def create_merkle_snapshot(
        self,
        period_start: datetime,
        period_end: datetime,
        created_by: Optional[UUID] = None,
    ) -> MerkleTreeSnapshot:
        """Create a Merkle tree snapshot for a period."""
        # Get integrity records in period
        result = await self.db.execute(
            select(AuditLogIntegrity)
            .where(
                AuditLogIntegrity.created_at >= period_start,
                AuditLogIntegrity.created_at <= period_end,
            )
            .order_by(AuditLogIntegrity.sequence)
        )
        integrity_records = result.scalars().all()
        
        # Extract leaf hashes in order
        leaf_hashes = [r.merkle_leaf_hash for r in integrity_records if r.merkle_leaf_hash]
        
        # Build Merkle tree
        tree = self._build_merkle_tree(leaf_hashes)
        
        # Create snapshot
        snapshot = MerkleTreeSnapshot(
            root_hash=tree["root"],
            tree_height=tree["height"],
            leaf_count=len(leaf_hashes),
            leaf_hashes=leaf_hashes,
            period_start=period_start,
            period_end=period_end,
            created_by=None,  # Would be passed in
        )
        
        self.db.add(snapshot)
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot
    
    async def get_merkle_proof(
        self,
        leaf_index: int,
        period_start: datetime,
        period_end: datetime,
    ) -> Optional[MerkleProof]:
        """Generate Merkle inclusion proof for a leaf."""
        # Get snapshot
        result = await self.db.execute(
            select(MerkleTreeSnapshot)
            .where(
                MerkleTreeSnapshot.period_start <= period_start,
                MerkleTreeSnapshot.period_end >= period_end,
            )
            .order_by(desc(MerkleTreeSnapshot.period_start))
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        
        if not snapshot or leaf_index >= snapshot.leaf_count:
            return None
        
        # Rebuild tree to generate proof
        tree = self._build_merkle_tree(snapshot.leaf_hashes)
        
        # Generate proof path
        siblings = []
        index = leaf_index
        for level in range(snapshot.tree_height):
            if index % 2 == 0:
                # Left child, sibling is right
                sibling_idx = index + 1
                position = "right"
            else:
                # Right child, sibling is left
                sibling_idx = index - 1
                position = "left"
            
            if sibling_idx < len(tree["levels"][level]):
                siblings.append({
                    "position": position,
                    "hash": tree["levels"][level][sibling_idx],
                })
            
            index //= 2
        
        return MerkleProof(
            leaf_hash=snapshot.leaf_hashes[leaf_index],
            leaf_index=leaf_index,
            root_hash=snapshot.root_hash,
            siblings=siblings,
            tree_height=snapshot.tree_height,
        )
    
    # -------------------------------------------------------------------------
    # CHAIN VERIFICATION
    # -------------------------------------------------------------------------
    
    async def verify_chain_integrity(
        self,
        start_sequence: int = 1,
        end_sequence: Optional[int] = None,
    ) -> VerificationResult:
        """Verify hash chain integrity."""
        query = select(AuditLogIntegrity).where(
            AuditLogIntegrity.sequence >= start_sequence
        )
        
        if end_sequence:
            query = query.where(AuditLogIntegrity.sequence <= end_sequence)
        
        query = query.order_by(AuditLogIntegrity.sequence)
        result = await self.db.execute(query)
        records = result.scalars().all()
        
        if not records:
            return VerificationResult(
                status=VerificationStatus.INCOMPLETE,
                proof_type=ProofType.HASH_CHAIN,
                verified_count=0,
                total_count=0,
                details={"reason": "No records found"},
            )
        
        tampered = []
        prev_chain_hash = "0" * 64
        prev_sequence = 0
        
        for i, record in enumerate(records):
            expected_sequence = start_sequence + i
            
            # Check sequence continuity
            if record.sequence != expected_sequence:
                tampered.append({
                    "sequence": record.sequence,
                    "expected_sequence": expected_sequence,
                    "audit_log_id": str(record.audit_log_id),
                    "issue": "SEQUENCE_GAP",
                })
            
            # Recompute entry hash from audit log
            audit_log_result = await self.db.execute(
                select(AuditLog).where(AuditLog.id == record.audit_log_id)
            )
            audit_log = audit_log_result.scalar_one_or_none()
            
            if not audit_log:
                tampered.append({
                    "sequence": record.sequence,
                    "audit_log_id": str(record.audit_log_id),
                    "issue": "AUDIT_LOG_MISSING",
                })
                continue
            
            computed_entry_hash = self._compute_entry_hash(audit_log)
            
            # Verify entry hash
            if record.entry_hash != computed_entry_hash:
                tampered.append({
                    "sequence": record.sequence,
                    "audit_log_id": str(record.audit_log_id),
                    "issue": "ENTRY_HASH_MISMATCH",
                    "expected": computed_entry_hash,
                    "actual": record.entry_hash,
                })
            
            # Verify chain hash
            expected_chain_hash = self._compute_chain_hash(prev_chain_hash, computed_entry_hash)
            if record.chain_hash != expected_chain_hash:
                tampered.append({
                    "sequence": record.sequence,
                    "audit_log_id": str(record.audit_log_id),
                    "issue": "CHAIN_HASH_MISMATCH",
                    "expected": expected_chain_hash,
                    "actual": record.chain_hash,
                })
            
            prev_chain_hash = record.chain_hash
            prev_sequence = record.sequence
        
        verified = len(records) - len(tampered)
        status = VerificationStatus.VALID if not tampered else VerificationStatus.TAMPERED
        
        return VerificationResult(
            status=status,
            proof_type=ProofType.HASH_CHAIN,
            verified_count=verified,
            total_count=len(records),
            tampered_entries=tampered,
            details={
                "start_sequence": start_sequence,
                "end_sequence": end_sequence or records[-1].sequence,
                "chain_head": records[-1].chain_hash if records else "0" * 64,
            },
        )
    
    # -------------------------------------------------------------------------
    # MERKLE TREE VERIFICATION
    # -------------------------------------------------------------------------
    
    async def verify_merkle_inclusion(
        self,
        audit_log_id: UUID,
    ) -> VerificationResult:
        """Verify a specific audit log entry is included in Merkle tree."""
        # Get integrity record
        result = await self.db.execute(
            select(AuditLogIntegrity).where(AuditLogIntegrity.audit_log_id == audit_log_id)
        )
        integrity = result.scalar_one_or_none()
        
        if not integrity or not integrity.merkle_leaf_hash:
            return VerificationResult(
                status=VerificationStatus.INCOMPLETE,
                proof_type=ProofType.MERKLE_ROOT,
                verified_count=0,
                total_count=1,
                details={"reason": "No Merkle leaf hash available"},
            )
        
        # Get snapshot for the period
        result = await self.db.execute(
            select(MerkleTreeSnapshot)
            .where(
                MerkleTreeSnapshot.period_start <= integrity.created_at,
                MerkleTreeSnapshot.period_end >= integrity.created_at,
            )
            .order_by(desc(MerkleTreeSnapshot.period_start))
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        
        if not snapshot:
            return VerificationResult(
                status=VerificationStatus.INCOMPLETE,
                proof_type=ProofType.MERKLE_ROOT,
                verified_count=0,
                total_count=1,
                details={"reason": "No Merkle snapshot for period"},
            )
        
        # Verify leaf hash is in snapshot
        if integrity.merkle_leaf_hash not in snapshot.leaf_hashes:
            return VerificationResult(
                status=VerificationStatus.TAMPERED,
                proof_type=ProofType.MERKLE_ROOT,
                verified_count=0,
                total_count=1,
                details={"reason": "Leaf hash not in snapshot"},
            )
        
        # Generate and verify Merkle proof
        leaf_index = snapshot.leaf_hashes.index(integrity.merkle_leaf_hash)
        proof = await self.get_merkle_proof(leaf_index, snapshot.period_start, snapshot.period_end)
        
        if not proof:
            return VerificationResult(
                status=VerificationStatus.INCOMPLETE,
                proof_type=ProofType.INCLUSION,
                verified_count=0,
                total_count=1,
                details={"reason": "Could not generate Merkle proof"},
            )
        
        # Verify proof
        computed_root = self._verify_merkle_proof(proof)
        if computed_root != snapshot.root_hash:
            return VerificationResult(
                status=VerificationStatus.TAMPERED,
                proof_type=ProofType.INCLUSION,
                verified_count=0,
                total_count=1,
                details={"reason": "Merkle proof verification failed"},
            )
        
        return VerificationResult(
            status=VerificationStatus.VALID,
            proof_type=ProofType.INCLUSION,
            verified_count=1,
            total_count=1,
            details={
                "leaf_index": leaf_index,
                "root_hash": snapshot.root_hash,
            },
        )
    
    def _verify_merkle_proof(self, proof: MerkleProof) -> str:
        """Verify Merkle proof and compute root hash."""
        current_hash = proof.leaf_hash
        
        for sibling in proof.siblings:
            if sibling["position"] == "left":
                combined = f"{sibling['hash']}:{current_hash}"
            else:
                combined = f"{current_hash}:{sibling['hash']}"
            current_hash = hashlib.sha256(combined.encode()).hexdigest()
        
        return current_hash
    
    # -------------------------------------------------------------------------
    # FULL VERIFICATION
    # -------------------------------------------------------------------------
    
    async def run_full_verification(
        self,
        period_start: datetime,
        period_end: datetime,
        initiated_by: Optional[UUID] = None,
    ) -> AuditIntegrityReport:
        """Run full integrity verification for a period."""
        log = IntegrityVerificationLog(
            verification_type="full",
            status=VerificationStatus.INCOMPLETE.value,
            period_start=period_start,
            period_end=period_end,
            started_at=datetime.now(timezone.utc),
            initiated_by=initiated_by,
        )
        self.db.add(log)
        await self.db.flush()
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # 1. Verify hash chain
            chain_result = await self.verify_chain_integrity()
            
            # 2. Verify Merkle snapshots
            snapshot_result = await self.db.execute(
                select(MerkleTreeSnapshot)
                .where(
                    MerkleTreeSnapshot.period_start >= period_start,
                    MerkleTreeSnapshot.period_end <= period_end,
                )
                .order_by(MerkleTreeSnapshot.period_start)
            )
            snapshots = result.scalars().all()
            
            snapshot_verified = 0
            snapshot_tampered = 0
            
            for snapshot in snapshots:
                # Verify each snapshot's Merkle tree
                tree = self._build_merkle_tree(snapshot.leaf_hashes)
                if tree["root"] == snapshot.root_hash:
                    snapshot_verified += 1
                else:
                    snapshot_tampered += 1
            
            # 3. Check for missing entries (sequence gaps)
            result = await self.db.execute(
                select(AuditLogIntegrity)
                .where(
                    AuditLogIntegrity.created_at >= period_start,
                    AuditLogIntegrity.created_at <= period_end,
                )
                .order_by(AuditLogIntegrity.sequence)
            )
            integrity_records = result.scalars().all()
            
            missing_count = 0
            expected_seq = 1
            if integrity_records:
                expected_seq = integrity_records[0].sequence
                for i, record in enumerate(integrity_records):
                    if record.sequence != expected_seq:
                        missing_count += (record.sequence - expected_seq)
                    expected_seq = record.sequence + 1
            
            # Compile results
            total_entries = len(integrity_records)
            verified_count = total_entries - chain_result.tampered_entries - snapshot_tampered
            tampered_count = len(chain_result.tampered_entries) + snapshot_tampered
            
            report = AuditIntegrityReport(
                report_id=uuid4(),
                period_start=period_start,
                period_end=period_end,
                total_entries=total_entries,
                verified_count=verified_count,
                tampered_count=tampered_count,
                missing_count=missing_count,
                merkle_root=snapshots[-1].root_hash if snapshots else "0" * 64,
                chain_head=integrity_records[-1].chain_hash if integrity_records else "0" * 64,
                verification_results=[chain_result],
                generated_at=datetime.now(timezone.utc),
            )
            
            # Update log
            log.status = VerificationStatus.VALID.value if tampered_count == 0 else VerificationStatus.TAMPERED.value
            log.total_entries = total_entries
            log.verified_count = verified_count
            log.tampered_count = tampered_count
            log.missing_count = missing_count
            log.merkle_root = report.merkle_root
            log.chain_head = report.chain_head
            log.tampered_entries = chain_result.tampered_entries
            log.completed_at = datetime.now(timezone.utc)
            log.duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            
            await self.db.commit()
            
            return report
            
        except Exception as e:
            log.status = VerificationStatus.INVALID.value
            log.error_message = str(e)
            log.completed_at = datetime.now(timezone.utc)
            log.duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            await self.db.commit()
            raise
    
    # -------------------------------------------------------------------------
    # INCREMENTAL VERIFICATION
    # -------------------------------------------------------------------------
    
    async def run_incremental_verification(
        self,
        last_verified_sequence: int,
    ) -> VerificationResult:
        """Verify integrity incrementally from last verified sequence."""
        return await self.verify_chain_integrity(start_sequence=last_verified_sequence + 1)


# =============================================================================
# ADMIN API FOR AUDIT INTEGRITY
# =============================================================================

audit_integrity_router = APIRouter(prefix="/admin/audit/integrity", tags=["Audit Integrity"])


@audit_integrity_router.post(
    "/verify/chain",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
)
async def verify_chain(
    request: dict,
    current_user: User = Depends(require_permission("audit:verify")),
    db: AsyncSession = Depends(get_db),
):
    """Verify hash chain integrity."""
    service = AuditIntegrityService(db)
    
    start_seq = request.get("start_sequence", 1)
    end_seq = request.get("end_sequence")
    
    result = await service.verify_chain_integrity(
        start_sequence=start_seq,
        end_sequence=end_seq,
    )
    
    return {
        "status": result.status.value,
        "verified_count": result.verified_count,
        "total_count": result.total_count,
        "tampered_count": len(result.tampered_entries),
        "tampered_entries": result.tampered_entries,
        "details": result.details,
    }


@audit_integrity_router.post(
    "/verify/merkle",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
)
async def verify_merkle_inclusion(
    request: dict,
    current_user: User = Depends(require_permission("audit:verify")),
    db: AsyncSession = Depends(get_db),
):
    """Verify Merkle inclusion proof for an audit log entry."""
    service = AuditIntegrityService(db)
    
    audit_log_id = UUID(request["audit_log_id"])
    result = await service.verify_merkle_inclusion(audit_log_id)
    
    return {
        "status": result.status.value,
        "verified": result.status == VerificationStatus.VALID,
        "details": result.details,
    }


@audit_integrity_router.post(
    "/verify/full",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_full_verification(
    request: dict,
    current_user: User = Depends(require_role("ADMIN", "COMPLIANCE")),
    db: AsyncSession = Depends(get_db),
):
    """Run full integrity verification for a period."""
    service = AuditIntegrityService(db)
    
    period_start = datetime.fromisoformat(request["period_start"])
    period_end = datetime.fromisoformat(request["period_end"])
    
    report = await service.run_full_verification(
        period_start=period_start,
        period_end=period_end,
        initiated_by=current_user.id,
    )
    
    return {
        "report_id": str(report.report_id),
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "total_entries": report.total_entries,
        "verified_count": report.verified_count,
        "tampered_count": report.tampered_count,
        "missing_count": report.missing_count,
        "merkle_root": report.merkle_root,
        "chain_head": report.chain_head,
        "status": "VALID" if report.tampered_count == 0 else "TAMPERED",
    }


@audit_integrity_router.post(
    "/snapshot/create",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def create_merkle_snapshot(
    request: dict,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Create a Merkle tree snapshot for a period."""
    service = AuditIntegrityService(db)
    
    period_start = datetime.fromisoformat(request["period_start"])
    period_end = datetime.fromisoformat(request["period_end"])
    
    snapshot = await service.create_merkle_snapshot(
        period_start=period_start,
        period_end=period_end,
        created_by=current_user.id,
    )
    
    return {
        "snapshot_id": str(snapshot.id),
        "root_hash": snapshot.root_hash,
        "tree_height": snapshot.tree_height,
        "leaf_count": snapshot.leaf_count,
        "period_start": snapshot.period_start.isoformat(),
        "period_end": snapshot.period_end.isoformat(),
    }


@audit_integrity_router.post(
    "/proof/inclusion",
    response_model=dict,
)
async def generate_inclusion_proof(
    request: dict,
    current_user: User = Depends(require_permission("audit:verify")),
    db: AsyncSession = Depends(get_db),
):
    """Generate Merkle inclusion proof for an audit log entry."""
    service = AuditIntegrityService(db)
    
    audit_log_id = UUID(request["audit_log_id"])
    
    # Get integrity record
    result = await db.execute(
        select(AuditLogIntegrity).where(AuditLogIntegrity.audit_log_id == UUID(request["audit_log_id"]))
    )
    integrity = result.scalar_one_or_none()
    
    if not integrity or not integrity.merkle_leaf_hash:
        raise HTTPException(status_code=404, detail="No Merkle leaf hash available")
    
    # Get snapshot
    result = await db.execute(
        select(MerkleTreeSnapshot)
        .where(
            MerkleTreeSnapshot.period_start <= integrity.created_at,
            MerkleTreeSnapshot.period_end >= integrity.created_at,
        )
        .order_by(desc(MerkleTreeSnapshot.period_start))
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    
    if not snapshot:
        raise HTTPException(status_code=404, detail="No Merkle snapshot for period")
    
    # Generate proof
    leaf_index = snapshot.leaf_hashes.index(integrity.merkle_leaf_hash)
    service = AuditIntegrityService(db)
    proof = await service.get_merkle_proof(leaf_index, snapshot.period_start, snapshot.period_end)
    
    return {
        "audit_log_id": str(audit_log_id),
        "leaf_index": proof.leaf_index,
        "leaf_hash": proof.leaf_hash,
        "root_hash": proof.root_hash,
        "siblings": proof.siblings,
        "tree_height": proof.tree_height,
    }