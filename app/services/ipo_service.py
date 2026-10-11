from typing import List, Optional, Tuple
from sqlalchemy import select, func, desc, asc, or_, case
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.ipo_timeline import get_ist_today

from app.models.ipo import (
    IPO,
    IPOSubscription,
    IPOGmp,
    IPOScore,
    IPOStatus,
    IPOType,
    RecommendationType
)
from app.schemas.ipo import IPOCreate, IPOUpdate, SubscriptionCreate, GMPCreate
from app.services.scoring_service import ScoringService


class IPOService:
    @staticmethod
    async def get_ipo_by_id(session: AsyncSession, ipo_id: int) -> Optional[IPO]:
        stmt = (
            select(IPO)
            .where(IPO.id == ipo_id)
            .options(
                selectinload(IPO.subscriptions),
                selectinload(IPO.gmp_records),
                selectinload(IPO.score),
                selectinload(IPO.documents),
                selectinload(IPO.anchor_investors),
                selectinload(IPO.reviews_summary),
                selectinload(IPO.listing_info),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_ipo_by_symbol(session: AsyncSession, symbol: str) -> Optional[IPO]:
        stmt = (
            select(IPO)
            .where(func.upper(IPO.symbol) == symbol.strip().upper())
            .options(
                selectinload(IPO.subscriptions),
                selectinload(IPO.gmp_records),
                selectinload(IPO.score),
                selectinload(IPO.documents),
                selectinload(IPO.anchor_investors),
                selectinload(IPO.reviews_summary),
                selectinload(IPO.listing_info),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_ipos(
        session: AsyncSession,
        status: Optional[IPOStatus] = None,
        ipo_type: Optional[IPOType] = None,
        recommendation: Optional[RecommendationType] = None,
        min_score: Optional[float] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
        include_seed: bool = False
    ) -> Tuple[List[IPO], int]:
        stmt = (
            select(IPO)
            .outerjoin(IPO.score)
            .options(
                selectinload(IPO.subscriptions),
                selectinload(IPO.gmp_records),
                selectinload(IPO.score),
                selectinload(IPO.documents),
                selectinload(IPO.anchor_investors),
                selectinload(IPO.reviews_summary),
                selectinload(IPO.listing_info),
            )
        )

        count_stmt = select(func.count(IPO.id)).outerjoin(IPO.score)

        # 1. Hide seed rows from user-facing queries unless explicitly requested
        if not include_seed:
            stmt = stmt.where(IPO.is_seed.is_(False))
            count_stmt = count_stmt.where(IPO.is_seed.is_(False))

        # 2. Status filtering & upcoming boundary enforcement
        if status:
            stmt = stmt.where(IPO.status == status)
            count_stmt = count_stmt.where(IPO.status == status)

            if status == IPOStatus.UPCOMING:
                today = get_ist_today()
                # The 'Upcoming' filter returns only IPOs with open_date >= today or dates_tba
                upcoming_cond = or_(IPO.open_date >= today, IPO.dates_tba.is_(True))
                stmt = stmt.where(upcoming_cond)
                count_stmt = count_stmt.where(upcoming_cond)
        else:
            stmt = stmt.where(IPO.status != IPOStatus.LISTED)
            count_stmt = count_stmt.where(IPO.status != IPOStatus.LISTED)

        if ipo_type:
            stmt = stmt.where(IPO.ipo_type == ipo_type)
            count_stmt = count_stmt.where(IPO.ipo_type == ipo_type)

        if recommendation:
            stmt = stmt.where(IPOScore.recommendation == recommendation)
            count_stmt = count_stmt.where(IPOScore.recommendation == recommendation)

        if min_score is not None:
            stmt = stmt.where(IPOScore.composite_score >= min_score)
            count_stmt = count_stmt.where(IPOScore.composite_score >= min_score)

        if search:
            search_filter = or_(
                IPO.symbol.ilike(f"%{search}%"),
                IPO.company_name.ilike(f"%{search}%")
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        total_count = (await session.execute(count_stmt)).scalar() or 0

        # 3. Sorting: Upcoming sorted by open_date ascending, with "Dates not announced" group at the end
        if status == IPOStatus.UPCOMING:
            stmt = stmt.order_by(
                case((IPO.dates_tba.is_(True), 1), (IPO.open_date.is_(None), 1), else_=0).asc(),
                asc(IPO.open_date),
                desc(IPO.created_at)
            ).offset(skip).limit(limit)
        else:
            stmt = stmt.order_by(desc(IPO.open_date), desc(IPO.created_at)).offset(skip).limit(limit)

        result = await session.execute(stmt)
        items = result.scalars().all()

        return list(items), total_count

    @staticmethod
    async def create_ipo(session: AsyncSession, data: IPOCreate) -> IPO:
        ipo_dict = data.model_dump()
        open_d = ipo_dict.get("open_date")
        close_d = ipo_dict.get("close_date")
        dq = ipo_dict.get("data_quality") or {}
        if close_d and open_d and close_d < open_d:
            ipo_dict["open_date"] = None
            ipo_dict["close_date"] = None
            missing = dq.get("missing_fields", [])
            if "invalid_dates" not in missing:
                missing.append("invalid_dates")
            dq["missing_fields"] = missing
            dq["status"] = "incomplete"
            ipo_dict["data_quality"] = dq

        from app.core.ipo_timeline import derive_ipo_status
        if ipo_dict.get("open_date") and ipo_dict.get("close_date"):
            ipo_dict["status"] = derive_ipo_status(
                ipo_dict.get("open_date"),
                ipo_dict.get("close_date"),
                ipo_dict.get("listing_date")
            )
        elif not ipo_dict.get("status"):
            ipo_dict["status"] = derive_ipo_status(
                ipo_dict.get("open_date"),
                ipo_dict.get("close_date"),
                ipo_dict.get("listing_date")
            )

        ipo = IPO(**ipo_dict)
        session.add(ipo)
        await session.flush()

        # Compute initial baseline score
        score_data = ScoringService.calculate_score(ipo=ipo)
        valid_keys = {"composite_score", "recommendation", "gmp_score", "subscription_score", "valuation_score", "structure_score", "rationale"}
        score_dict = {k: v for k, v in score_data.items() if k in valid_keys}
        score_obj = IPOScore(ipo_id=ipo.id, **score_dict)
        session.add(score_obj)
        await session.commit()
        await session.refresh(ipo)
        return await IPOService.get_ipo_by_id(session, ipo.id)  # type: ignore

    @staticmethod
    async def update_ipo(session: AsyncSession, ipo: IPO, data: IPOUpdate) -> IPO:
        update_dict = data.model_dump(exclude_unset=True)
        for key, val in update_dict.items():
            setattr(ipo, key, val)

        if ipo.close_date and ipo.open_date and ipo.close_date < ipo.open_date:
            ipo.open_date = None
            ipo.close_date = None
            dq = ipo.data_quality or {}
            missing = dq.get("missing_fields", [])
            if "invalid_dates" not in missing:
                missing.append("invalid_dates")
            dq["missing_fields"] = missing
            dq["status"] = "incomplete"
            ipo.data_quality = dq

        from app.core.ipo_timeline import derive_ipo_status
        if ipo.open_date and ipo.close_date:
            ipo.status = derive_ipo_status(ipo.open_date, ipo.close_date, ipo.listing_date)
        await session.flush()

        # Recalculate score on update
        latest_sub = ipo.subscriptions[0] if ipo.subscriptions else None
        latest_gmp = ipo.gmp_records[0] if ipo.gmp_records else None
        score_data = ScoringService.calculate_score(ipo, latest_sub, latest_gmp)
        valid_keys = {"composite_score", "recommendation", "gmp_score", "subscription_score", "valuation_score", "structure_score", "rationale"}
        score_dict = {k: v for k, v in score_data.items() if k in valid_keys}

        if ipo.score:
            for k, v in score_dict.items():
                setattr(ipo.score, k, v)
        else:
            ipo.score = IPOScore(ipo_id=ipo.id, **score_dict)

        await session.commit()
        await session.refresh(ipo)
        return ipo

    @staticmethod
    async def delete_ipo(session: AsyncSession, ipo: IPO) -> None:
        await session.delete(ipo)
        await session.commit()

    @staticmethod
    async def add_subscription(session: AsyncSession, ipo_id: int, data: SubscriptionCreate) -> IPOSubscription:
        ipo = await IPOService.get_ipo_by_id(session, ipo_id)
        if not ipo:
            raise ValueError(f"IPO with id {ipo_id} not found")

        sub = IPOSubscription(ipo_id=ipo_id, **data.model_dump())
        session.add(sub)
        await session.flush()

        # Recalculate score
        latest_gmp = ipo.gmp_records[0] if ipo.gmp_records else None
        score_data = ScoringService.calculate_score(ipo, sub, latest_gmp)
        valid_keys = {"composite_score", "recommendation", "gmp_score", "subscription_score", "valuation_score", "structure_score", "rationale"}
        score_dict = {k: v for k, v in score_data.items() if k in valid_keys}

        if ipo.score:
            for k, v in score_dict.items():
                setattr(ipo.score, k, v)
        else:
            session.add(IPOScore(ipo_id=ipo_id, **score_dict))

        await session.commit()
        await session.refresh(sub)
        return sub

    @staticmethod
    async def add_gmp(session: AsyncSession, ipo_id: int, data: GMPCreate) -> IPOGmp:
        ipo = await IPOService.get_ipo_by_id(session, ipo_id)
        if not ipo:
            raise ValueError(f"IPO with id {ipo_id} not found")

        gmp = IPOGmp(ipo_id=ipo_id, **data.model_dump())
        session.add(gmp)
        await session.flush()

        # Recalculate score
        latest_sub = ipo.subscriptions[0] if ipo.subscriptions else None
        score_data = ScoringService.calculate_score(ipo, latest_sub, gmp)
        valid_keys = {"composite_score", "recommendation", "gmp_score", "subscription_score", "valuation_score", "structure_score", "rationale"}
        score_dict = {k: v for k, v in score_data.items() if k in valid_keys}

        if ipo.score:
            for k, v in score_dict.items():
                setattr(ipo.score, k, v)
        else:
            session.add(IPOScore(ipo_id=ipo_id, **score_dict))

        await session.commit()
        await session.refresh(gmp)
        return gmp

    @staticmethod
    async def recalculate_score(session: AsyncSession, ipo_id: int) -> IPOScore:
        ipo = await IPOService.get_ipo_by_id(session, ipo_id)
        if not ipo:
            raise ValueError(f"IPO with id {ipo_id} not found")

        latest_sub = ipo.subscriptions[0] if ipo.subscriptions else None
        latest_gmp = ipo.gmp_records[0] if ipo.gmp_records else None
        score_data = ScoringService.calculate_score(ipo, latest_sub, latest_gmp)

        valid_fields = {"composite_score", "recommendation", "gmp_score", "subscription_score", "valuation_score", "structure_score", "rationale"}
        filtered_data = {k: v for k, v in score_data.items() if k in valid_fields}

        if ipo.score:
            for k, v in filtered_data.items():
                setattr(ipo.score, k, v)
            score_obj = ipo.score
        else:
            score_obj = IPOScore(ipo_id=ipo_id, **filtered_data)
            session.add(score_obj)

        await session.commit()
        await session.refresh(score_obj)
        return score_obj
