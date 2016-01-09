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
I thought about creating speaker as its own class which could be useful in order to define more information about the speaker but decided that it didn't actually need that the conference central app in my eyes is to be used as a more organizational type tool so having more information about a speaker wouldnt be necessary. When logging on and recording that you're organizing and attending an event you really just need to know who your speaker is, That being said, I defined the speaker as a string

##Task 3
Query - getConferenceSessionByName

gets the session by the name of the session that way you can find what your looking for if you already have the session data rather than sifting through all sessions or types to find the one you already know

Query - getConferenceSessionByDate

this query task is to get all the sessions that occur on a given date.



these two queries are useful because if someone is looking to attend a session of a particular name they have the ability to search by it or date they can find what is going on and join accordingly. 


Query Problem. 
I believe the issue can be solved using the combinations of both of the two queries \. You could collect all of the sessions on a span of days and based on that query collect all of the sessions that occur before 1900 hours. These queries dont touch is session type, So i guess the solution would just require one more query which then based off the previous queries gets all the sessions of non workshop type.