from django.db import transaction
from django.db.models import Q
from django_q.tasks import schedule, Schedule
from sentry_sdk import capture_exception

from corporations.models import Corporation, Registration
from notifications.util import send_residences_notification, send_reactions_notification
from profiles.models import Profile
from profiles.util import get_age
from residences.models import Residence, Reaction
from woningzoeker.logging import logger

from .scrapers import scrapers, scrapers_by_name


def add_schedule(name: str, func, **kwargs):
    if not Schedule.objects.filter(name=name).first():
        schedule(func, name=name, **kwargs)


def initialize_tasks():
    add_schedule('scrape_residences', 'corporations.tasks.scrape_residences',
                 schedule_type=Schedule.CRON, cron='00 */2 * * *')

    add_schedule('scrape_reactions', 'corporations.tasks.scrape_reactions',
                 schedule_type=Schedule.CRON, cron='00 */6 * * *')


def scrape_residences():
    logger.info('Scraping residences')

    # Loop over all scrapers
    for scraper_class in scrapers:
        scraper = scraper_class()
        new_residence_ids: list[str] = []

        try:
            with transaction.atomic():
                # Find platform
                platform = Corporation.objects.filter(handle=scraper.get_handle()).first()
                if not platform:
                    raise Exception(f'Unknown platform "{scraper.get_handle()}"')

                logger.info(f'Scraping residences at platform "{platform.name}"')

                # Scrape residences
                scraper.start_session()
                residences = scraper.get_residences()
                scraper.end_session()

                # Loop over all scraped residences
                for residence in residences:
                    if not hasattr(residence, 'corporation'):
                        raise Exception(f'Residence "{residence.external_id}" is missing a corporation at platform "{platform}"')

                    # Check if the residence already exists
                    if Residence.objects.filter(external_id=residence.external_id, corporation=residence.corporation).count() > 0:
                        continue

                    # Create the residence
                    residence.save()

                    # Add city to corporation
                    residence.corporation.cities.add(residence.city)
                    residence.corporation.save()

                    new_residence_ids.append(residence.id)

            # Loop over profiles
            profiles = Profile.objects.all()
            for profile in profiles:
                age = get_age(profile)

                # Find new residences based on profile
                new_residences = Residence.objects\
                    .filter(id__in=new_residence_ids, corporation__platforms__registrations__user=profile.user)\
                    .filter(price_base__gte=profile.min_price_base, city__in=profile.cities.all())\
                    .filter(Q(min_age__isnull=True) | Q(min_age__lte=age), Q(max_age__isnull=True) | Q(max_age__gte=age))

                if profile.max_price_base > 0:
                    new_residences = new_residences.filter(price_base__lte=profile.max_price_base)

                # Send notification to user
                new_residences = new_residences.all()
                if len(new_residences) > 0:
                    send_residences_notification(profile.user, new_residences)
        except Exception as err:
            logger.error(f'Failed to scrape using scraper "{type(scraper).__name__}":')
            logger.exception(err)
            capture_exception(err)

        print('Finished scraping residences')


def scrape_reactions():
    logger.info('Scraping reactions')

    # Fetch registrations
    registrations = Registration.objects.all()

    # Loop over all registrations
    for registration in registrations:
        # Lookup the scraper
        scraper_class = scrapers_by_name[registration.platform.handle]
        if not scraper_class:
            raise Exception(f'Unknown scraper "{registration.platform.handle}"')

        scraper = scraper_class()
        new_reactions: list[Reaction] = []

        logger.info(f'Scraping reactions for "{registration.user.username}" at platform "{registration.platform}"')

        try:
            with transaction.atomic():
                # Log the user in
                scraper.start_session()
                scraper.login(registration.identifier, registration.credentials)

                # Scrape reactions
                scraped_reactions = scraper.get_reactions()

                # Loop over all reactions
                for scraped_reaction in scraped_reactions:
                    # Find the residence
                    residence = Residence.objects.filter(
                        external_id=scraped_reaction['external_id'],
                        corporation=Corporation.objects.get(handle=scraped_reaction['corporation_handle'])
                    ).first()

                    if not residence:
                        try:
                            # Attempt to scrape the residence
                            logger.info('Scraping residence "{0}" at platform "{1}"'.format(scraped_reaction['external_id'], registration.platform.name))
                            residence = scraper.get_residence(scraped_reaction['external_id'])
                            if residence:
                                # Create the residence
                                residence.platform = registration.platform
                                residence.save()
                            else:
                                logger.info('Residence "{0}" at platform "{1}" does not exist.'.format(scraped_reaction['external_id'],
                                                                                                       registration.platform.name))
                                continue
                        except Exception as err:
                            logger.error(f'Failed to scrape using scraper "{type(scraper).__name__}":')
                            logger.exception(err)
                            capture_exception(err)
                            continue

                    # Check if the reaction already exists
                    reaction = Reaction.objects.filter(residence=residence, registration=registration).first()
                    if not reaction:
                        # Create the reaction
                        reaction = Reaction(
                            created_at=scraped_reaction['created_at'],
                            registration=registration,
                            residence=residence
                        )
                    else:
                        # Check if the reaction has a new rank number
                        if reaction.rank_number is None and scraped_reaction['rank_number'] is not None:
                            new_reactions.append(reaction)

                    # Update reaction rank number
                    reaction.rank_number = scraped_reaction['rank_number']
                    reaction.save()

                    # Update the reactions end timestamp if necessary
                    if scraped_reaction['ended_at'] and not residence.reactions_ended_at:
                        residence.reactions_ended_at = scraped_reaction['ended_at']
                        residence.save()

                # Log the user out
                scraper.logout()
                scraper.end_session()

            if len(new_reactions) > 0:
                send_reactions_notification(registration.user, new_reactions)
        except Exception as err:
            logger.error(f'Failed to scrape using scraper "{type(scraper).__name__}":')
            logger.exception(err)
            capture_exception(err)

    logger.info('Finished scraping reactions')
