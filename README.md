App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
have registered in the App Engine admin console and would like to use to host
your instance of this sample.
1. Update the values at the top of `settings.py` to
reflect the respective client IDs you have registered in the
[Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
`$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool



##Task 1
Sessions are implemented as children of conferences and rely on their conference key to exist and be located. That way we can always find and organize the created sessions by their associated conferences. This just makes sense, the sessions only exist as part of a conference otherwise they dont really mean anything. Because of that as far as a design choice goes it only made sense to create sessions that solely rely on their parent conference rather than be free floating. I thought about creating speaker as its own class which could be useful in order to define more information about the speaker but decided that it didn't actually need that the conference central app in my eyes is to be used as a more organizational type tool so having more information about a speaker wouldnt be necessary. When logging on and recording that you're organizing and attending an event you really just need to know who your speaker is, That being said, I defined the speaker as a string.


createSession -> create a new session as a part of the given conference

getConferenceSessions -> get all of the sessions associated with a given conference 

getConferenceSessionsByType -> get all of the sessions by type with a given conference

getConferenceSessionsBySpeaker -> get all of the sessions by speaker

getConferenceSessionsByName -> get all of the sessions by Name with a given conference

getConferenceSessionsByDate -> get all of the sessions by Date with a given conference





##Task 3
Query - getConferenceSessionByName

gets the session by the name of the session that way you can find what your looking for if you already have the session data rather than sifting through all sessions or types to find the one you already know

Query - getConferenceSessionByDate

this query task is to get all the sessions that occur on a given date.



these two queries are useful because if someone is looking to attend a session of a particular name they have the ability to search by it or date they can find what is going on and join accordingly. 

Query Problem. 
The Query problem is that it involved querying with inequalities, in that app engine, specifically datastore cannot handle mutliple inequality filters. 

One of the solutions to this problem is to change how you view it and query it. Instead of searching for != workshops you can just specifically query all the other types of sessions. So this a more comlicated query in some respects because its bigger but solved the problem by stating the inverse of the inequality.  
-> to expand: 
instead of searching for 
session.type != workshop && session.time != 7 (altered for simplicity)
you can use the inverse of one of the queries that way only one inequality is used. The Documentation defines that use of mutliple inequalities is not allowed. that being said a query where the session type of what is being searched for rather than what is not, is being used.
session.type === [lecture, powerpoint....] && session.time != 7 (altered for simplicity)
--> if this does not solve the problem you can impliment it using a few different queries 
the first query, queries all sessions returns the keys that arent workshops 
the second query, queries previous keys for sessions before 7 

