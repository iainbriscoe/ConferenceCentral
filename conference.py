#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize

from models import Session
from models import SessionForm
from models import SessionForms
from models import SessionsByTypeForm
from models import SessionsByNameForm
from models import SessionsByDurationForm
from models import SessionsBySpeakerForm
from models import WishlistForm

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
MEMCACHE_SPEAKER_KEY = "FEATURED_SPEAKER"
SPEAKER_TPL = ('The featured speaker for this session is: %s!')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

SESSION_DEFAULTS = {
    "highlights": "To Be Announced",
    "speaker": "To Be Announced",
    "duration": 60,
    "typeOfSession": "To Be Announced",
}


OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -



SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)

SESSION_GET_TYPE_REQUEST = endpoints.ResourceContainer(
    typeOfSession=messages.StringField(1),
    websafeConferenceKey=messages.StringField(2),
)


SESS_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESS_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city=="London")
        q = q.filter(Conference.topics=="Medical Innovations")
        q = q.filter(Conference.month==6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

# - - - Sessions - - - - - - - - - - - - - - - - - - - -
#created using the following sources:
# large sections of the Conference objects 
# Udacity forms and the code contained within/as well as the contained links: 
#	- https://discussions.udacity.com/t/task-1-create-a-session/33294/5
# 	- https://discussions.udacity.com/t/p4-createsession/42195/7
#	- https://discussions.udacity.com/t/error-deleting-the-websafekey-from-sessionform-to-make-a-session/42212/3
# 	- https://discussions.udacity.com/t/createsession-sessionform-websafeconferencekey-what-should-be-the-request-class/41297
    def _createSessionObject(self, request):
        """Create Session Object, w/ createSession method returns the request ."""
        #get the current user logged in
        user = endpoints.get_current_user()
        #if there is not a user logged in currently
        if not user:
        	#advise auth is requried to proceed
            raise endpoints.UnauthorizedException('User Authorization required')
        #-----user exists--------
        #get user id from user object
        user_id = getUserId(user)
        #if the name field has not been filled 
        if not request.name:
            raise endpoints.BadRequestException("The session field 'name' is required")
        #if the websafe conference field has not been filled
        if not request.websafeConferenceKey:
            raise endpoints.BadRequestException("The session field 'websafeConferenceKey' is required")
        #get the conference assosiated with the provided websafeconferencekey
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        #if the conference is not found given the provided websafeconferencekey 
        if not conf:
            raise endpoints.NotFoundException(
                "A conference could not be found with the conference key: %s" % request.websafeConferenceKey)
        #if the user who is logged in is not the origional creater of the conference
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                "The maker of the conference is the only one that can update it.")
        #get the field data from the request
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['websafeConferenceKey']
        del data['conferenceName']

        for df in SESSION_DEFAULTS:
            if data[df] in (None, []):
                data[df] = SESSION_DEFAULTS[df]
                setattr(request, df, SESSION_DEFAULTS[df])
        #if the session has a date format it.
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
        #if the session has a start time format it. 
        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'][:5], "%H:%M").time()

        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key

        Session(**data).put()
        #get the number of speakers 
        sessions = Session.query(Session.speaker == data['speaker']).count()
        #if there is more than one speaker set the featured
        if sessions > 1:
            taskqueue.add(params={'speaker': data['speaker']}, url='/tasks/set_featured_speaker')

        return self._copySessionToForm(request)

   
    def _copySessionToForm(self, session):
        """allocate data from Session to SessionForm."""
        #session form identification
        sf = SessionForm()
        #for all of the fields in session form 
        for field in sf.all_fields():
        	#if session has a field name
            if hasattr(session, field.name):
            	#if theirs a date set it
                if field.name == 'date':
                    setattr(sf, field.name, str(getattr(session, field.name)))
                #if theirs a time set it
                elif field.name == 'startTime':
                    setattr(sf, field.name, str(getattr(session, field.name)))
                #if not time and date set name
                else:
                    setattr(sf, field.name, getattr(session, field.name))
            #no field name
            elif field.name == "websafeKey":
            	#set name as websafekey
                setattr(sf, field.name, session.key.urlsafe())
        sf.check_initialized()
        return sf


    
    @endpoints.method(SESS_POST_REQUEST, SessionForm,
                      path = 'session',
                      http_method = 'POST',
                      name = 'createSession')
    def createSession(self, request):
        """Create a new session."""
        #pass request data to _createSessionObject
        return self._createSessionObject(request)

    @endpoints.method(SESS_GET_REQUEST, SessionForms,
            path='sessions/get/{websafeConferenceKey}',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """get the sessions in a conference."""
        #the conference via the websafeconferenceKey
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get().key
        #the session contained withing the conference 
        sessions = Session.query(ancestor=conf)
        #return the fields contained within session 
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SessionsByTypeForm, SessionForms,
            path='session/type/{websafeConferenceKey}',
            http_method='GET',
            name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Get conference sessions by the type of session"""
        #get all of the sessions with the specified type 
        sessions = Session.query(Session.typeOfSession == request.typeOfSession)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SessionsBySpeakerForm, SessionForms,
            path='speaker',
            http_method='GET',
            name='getConferenceSessionsBySpeaker')
    def getConferenceSessionsBySpeaker(self, request):
        """Get the conference sessions by the name of speaker."""
        #get all of the sessions with a given speaker 
        sessions = Session.query(Session.speaker == request.speaker)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )


    @endpoints.method(SessionsByNameForm, SessionForms,
            path='session/name/{websafeConferenceKey}',
            http_method='GET',
            name='getConferenceSessionsByName')
    def getConferenceSessionsByName(self, request):
        """Get conference sessions by the name of session """
        #get all of the sessions with the specified name 
        sessions = Session.query(Session.name == request.name)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SessionsByDateForm, SessionForms,
            path='session/date/{websafeConferenceKey}',
            http_method='GET',
            name='getConferenceSessionsByDate')
    def getConferenceSessionsByDate(self, request):
        """Get conference sessions by the date of the session ."""
        #get all of the sessions with the given duraction
        sessions = Session.query(Session.date == request.date)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )
       

# - - - Wishlists - - - - - - - - - - - - - - - - -
    @endpoints.method(WishlistForm, ProfileForm,
                      path="profile/addSessionToWishlist",
                      http_method="POST",
                      name="addSessionToWishlist")
    def addSessionToWishlist(self, request):
        """Add existing session to current users wishlist """
        #get current user 
        currentUser = endpoints.get_current_user()
        #if user is not logged in 
        if not currentUser:
            raise endpoints.UnauthorizedException('User authorization is required')
        #get current users profile 
        profile = self._getProfileFromUser()
        #websafekey of the given session 
        websafe_key = request.websafeSessionKey
        #could fail due to key not existing, or inability to decode
        try:
        	#strip key 
            websafe_key = ndb.Key(urlsafe=websafe_key)
            #if the key is not already in the users session wishlist - add it 
            if websafe_key not in profile.websafeSessionKey:
                return self._doProfile(request)
            #session already in wishlist
            else:
                return 'This session is already in your wishlist'
        except ProtocolBufferDecodeError:
            websafe_key = None


    @endpoints.method(WishlistForm, SessionForms,
                      path="profile/wishlist'",
                      name="getSessionsInWishlist")
    def getSessionsInWishlist(self, request):
        """Get the sessions a user has saved to their wishlist""" 
        #get current user       
        currentUser = endpoints.get_current_user()
        #if current user is not logged in 
        if not currentUser:
            raise endpoints.UnauthorizedException('User authorization is required')
        #profile of the currently logged in user 
        profile = self._getProfileFromUser()
        #key of the sessions in your wishlist 
        wishlistKeys = [ndb.Key(urlsafe=sessionKey) for sessionKey in profile.websafeSessionKey]
        #sessions given the wishlist keys 
        sessions = ndb.get_multi(wishlistKeys)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(WishlistForm, ProfileForm,
            path='profile/deleteSessionInWishlist',
            http_method='DELETE',
            name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        """remove a session from a users wishlist."""
        #get current user       
        currentUser = endpoints.get_current_user()
        #if current user is not logged in 
        if not currentUser:
            raise endpoints.UnauthorizedException('User authorization is required') 
        #get profile from currently logged in user       
        profile = self._getProfileFromUser()
        #get the session key for session to be removed from wishlist
        sessionKey = request.websafeSessionKey
        #if session is in wishlist remove it
        if sessionKey in profile.websafeSessionKey:
            return self._doProfile(request)
        #session is not in wishlist
        else:
            return 'This session is not in your wishlist. You cannot delete a session that is not in your wishlist'
#referenced udacity forms during conception


# - - - Featured Speaker - - - - - - - - - - - - - - - - -
#referenced Announcments and udacity forms during conception
    @staticmethod
    def _cacheSpeaker(speaker):
        """replace default featured speaker with anyone who is the speaker at more than one event""" 
        #get sessions for a given speaker
       	sessions = Session.query(Session.speaker == speaker).fetch()
       	#if the number of sessions they speak at is more than one
        if len(sessions) > 1:
            featuredSpeaker = (SPEAKER_TPL % speaker) + ' ' + 'Sessions:'
            for session in sessions:
                featuredSpeaker += ' ' + session.name
            memcache.set(MEMCACHE_SPEAKER_KEY, featuredSpeaker)
        #set featured feature from memcache 
        else:
            featuredSpeaker = (memcache.get(MEMCACHE_SPEAKER_KEY) or "")
        return featuredSpeaker

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/featSpeaker/get',
            http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """get featured speaker from memcache"""
        return StringMessage(data=memcache.get(MEMCACHE_SPEAKER_KEY) or "")


api = endpoints.api_server([ConferenceApi]) # register API