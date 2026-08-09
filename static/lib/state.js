// Shared state + constant maps for the dashboard.
//
// ES-module imports are live but read-only bindings, so a module can't reassign another
// module's exported `let`. Anything that gets *reassigned* (META, ROWS, REV, DRAG, drawerId)
// lives as a field on the single mutable `store` object; anything mutated *in place*
// (STATE, COLLAPSE, SECOFF) is exported directly.

export const A = {accent:"#4f7d4a",green:"#16a34a",blue:"#3b82f6",amber:"#d98e26",violet:"#8b5cf6",red:"#dc2626",gray:"#9ca3af"};
export const SCOLOR = {new:"#9ca3af",shortlisted:"#3b82f6",skip:"#b0b4bb",applied:"#4f7d4a",screening:"#d98e26",interviewing:"#8b5cf6",offer:"#16a34a",closed:"#dc2626",passed:"#9ca3af"};
export const PROG = {new:0,shortlisted:.25,skip:0,applied:.45,screening:.62,interviewing:.82,offer:1,closed:1,passed:1};
export const FITC = {5:"#16a34a",4:"#4f7d4a",3:"#d98e26",2:"#9ca3af",1:"#9ca3af"};
export const ACTC = {interview:"#8b5cf6",applied:"#4f7d4a",screening:"#d98e26",offer:"#16a34a",reject:"#dc2626",email:"#3b82f6",note:"#9ca3af"};
export const CHEV = '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M2.5 4L5 6.5 7.5 4" stroke="currentColor" fill="none" stroke-width="1.4" stroke-linecap="round"/></svg>';

// Reassigned globals -> fields on one mutable object.
export const store = {META:null, ROWS:[], REV:null, DRAG:null, drawerId:null};

// Filter/nav state + the two open sets (mutated in place, never reassigned).
export const STATE = {
  region:"", status:"", experience:"", source:"", q:"", sort:"fit",
  view: localStorage.getItem("v2view") || "home",
  listmode: localStorage.getItem("v2listmode") || "list",
  id:null, cursor:-1,
};
export const COLLAPSE = new Set();
export const SECOFF = new Set();

// Display lookups shared by the list + cards renderers.
export const WML = {remote:"Remote",hybrid:"Hybrid",onsite:"On-site"};
export const EXPL = {"mid":"Mid","mid-senior":"Mid–Senior","senior":"Senior","director":"Lead+","10-12yr":"Staff/Principal","principal":"Principal","lead":"Lead"};
export const SRCL = {"portal:greenhouse":"Greenhouse","portal:ashby":"Ashby","portal:lever":"Lever","portal:workable":"Workable","portal:recruitee":"Recruitee","portal:smartrecruiters":"SmartRecruiters","portal:rss":"RSS feed","portal:remoteok":"RemoteOK","portal:remotive":"Remotive","linkedin-search":"LinkedIn","manual":"Manual","gmail-sync":"Inbox","demo":"Demo"};
export const TAG_SKIP = new Set(["portal","greenhouse","ashby","lever","workable","recruitee","smartrecruiters","needs-jd","linkedin","gmail"]);
export function cleanLoc(l){return (l||"").replace(/\s*\((on-site|remote|hybrid)\)\s*$/i,"").trim();}
