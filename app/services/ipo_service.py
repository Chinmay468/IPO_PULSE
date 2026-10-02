from typing import List, Optional, Tuple
from sqlalchemy import select, func, desc, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

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
                selectinload(IPO.score)
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
                selectinload(IPO.score)
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
        limit: int = 50
    ) -> Tuple[List[IPO], int]:
        stmt = (
            select(IPO)
            .outerjoin(IPO.score)
            .options(
                selectinload(IPO.subscriptions),
                selectinload(IPO.gmp_records),
                selectinload(IPO.score)
            )
        )

        count_stmt = select(func.count(IPO.id)).outerjoin(IPO.score)

        if status:
            stmt = stmt.where(IPO.status == status)
            count_stmt = count_stmt.where(IPO.status == status)
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

        stmt = stmt.order_by(desc(IPO.open_date), desc(IPO.created_at)).offset(skip).limit(limit)
        result = await session.execute(stmt)
        items = result.scalars().all()

        return list(items), total_count

    @staticmethod
    async def create_ipo(session: AsyncSession, data: IPOCreate) -> IPO:
        ipo = IPO(**data.model_dump())
        session.add(ipo)
        await session.flush()

        # Compute initial baseline score
        score_data = ScoringService.calculate_score(ipo=ipo)
        score_obj = IPOScore(ipo_id=ipo.id, **score_data)
        session.add(score_obj)
        await session.commit()
        await session.refresh(ipo)
        return await IPOService.get_ipo_by_id(session, ipo.id)  # type: ignore

    @staticmethod
    async def update_ipo(session: AsyncSession, ipo: IPO, data: IPOUpdate) -> IPO:
        update_dict = data.model_dump(exclude_unset=True)
        for key, val in update_dict.items():
            setattr(ipo, key, val)
        await session.flush()

        # Recalculate score on update
        latest_sub = ipo.subscriptions[0] if ipo.subscriptions else None
        latest_gmp = ipo.gmp_records[0] if ipo.gmp_records else None
        score_data = ScoringService.calculate_score(ipo, latest_sub, latest_gmp)

        if ipo.score:
            for k, v in score_data.items():
                setattr(ipo.score, k, v)
        else:
            ipo.score = IPOScore(ipo_id=ipo.id, **score_data)

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

        if ipo.score:
            for k, v in score_data.items():
                setattr(ipo.score, k, v)
        else:
            session.add(IPOScore(ipo_id=ipo_id, **score_data))

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

        if ipo.score:
            for k, v in score_data.items():
                setattr(ipo.score, k, v)
        else:
            session.add(IPOScore(ipo_id=ipo_id, **score_data))

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

        if ipo.score:
            for k, v in score_data.items():
                setattr(ipo.score, k, v)
            score_obj = ipo.score
        else:
            score_obj = IPOScore(ipo_id=ipo_id, **score_data)
            session.add(score_obj)

        await session.commit()
        await session.refresh(score_obj)
        return score_obj
