import CryptoJS from "crypto-js";

// POST
const p = function (e) {
  var t = {},
    n = e.split("?")[1];
  return (
    n &&
      n.split("&").forEach(function (e) {
        var n = e.split("="),
          a = c()(n, 2),
          o = a[0],
          i = a[1];
        t[o] = decodeURIComponent(i);
      }),
    t
  );
};

const r = function (e) {
  return CryptoJS.MD5(e).toString(CryptoJS.enc.Hex);
};

const sign = function (e, t) {
  if (Object.keys(t).length > 0) {
    var n = Object.keys(t).sort(),
      a = n
        .map(function (e) {
          var n = t[e];
          return "string" == typeof n ? n.trimEnd() : String(n);
        })
        .filter(function (e) {
          return null !== e && void 0 !== e && "" !== e;
        })
        .join(","),
      i = e + "," + a + ",1e31af8c14999aa99d78537a8641ea4d",
      s = r(i);
    return s;
  }
  var c = e + ",1e31af8c14999aa99d78537a8641ea4d",
    u = r(c);
  return u;
};

const getSign = function (method = "", url = "") {
  const baseURL = "/ld_web";
  let Signature = "";
  if (method.toUpperCase() === "GET") {
    var n = Object.fromEntries(new URLSearchParams(url.split("?")[1] || ""));
    var a = new Date().getTime();
    var o = sign(a, n);
    Signature = a + ";" + o;
  } else {
    var i = p(url.replace(baseURL, ""));
    var r = new Date().getTime();
    var c = sign(r, i);
    Signature = r + ";" + c;
  }
  return Signature;
};

/**
fetch("https://cnvdb.org.cn/ld_web/policy?currentPage=1&pageSize=5", {
  "headers": {
    "accept": "application/json;charset=UTF-8",
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "access-control-allow-headers": "*",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "sec-ch-ua": "\"Not)A;Brand\";v=\"8\", \"Chromium\";v=\"138\", \"Google Chrome\";v=\"138\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"macOS\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "signature": "1760171350951;e71f90c8149b9713962b7c6ca886efc4",
    "Referer": "https://cnvdb.org.cn/"
  },
  "body": null,
  "method": "GET"
});
**/

/**
 * 调用 CNV 数据库政策接口获取数据
 * @param {number} currentPage - 当前页码，默认为1
 * @param {number} pageSize - 每页大小，默认为5
 * @returns {Promise<Object>} 返回接口响应数据
 */
export async function getCNVList(currentPage = 1, pageSize = 5) {
  try {
    // 构建URL和参数
    const baseUrl = "https://cnvdb.org.cn/ld_web/policy";
    const params = new URLSearchParams({
      currentPage: currentPage.toString(),
      pageSize: pageSize.toString(),
    });
    const fullUrl = `${baseUrl}?${params.toString()}`;
    // 获取签名
    const signature = getSign("GET", `/policy?${params.toString()}`);
    // 发送请求
    const response = await fetch(fullUrl, {
      method: "GET",
      headers: {
        accept: "application/json;charset=UTF-8",
        "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "access-control-allow-headers": "*",
        "cache-control": "no-cache",
        pragma: "no-cache",
        priority: "u=1, i",
        "sec-ch-ua":
          '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        signature: signature,
        Referer: "https://cnvdb.org.cn/",
      },
    });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    return data;
  } catch (error) {
    console.error("获取CNV数据失败:", error);
    throw error;
  }
}

export async function getCNVDetail(id = "") {
  try {
    // 构建URL和参数
    const baseUrl = "https://cnvdb.org.cn/ld_web/policy/getById";
    const params = new URLSearchParams({
      id: id.toString(),
    });
    const fullUrl = `${baseUrl}?${params.toString()}`;
    // 获取签名
    const signature = getSign("GET", `/policy/getById?${params.toString()}`);
    // 发送请求
    const response = await fetch(fullUrl, {
      method: "GET",
      headers: {
        accept: "application/json;charset=UTF-8",
        "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "access-control-allow-headers": "*",
        "cache-control": "no-cache",
        pragma: "no-cache",
        priority: "u=1, i",
        "sec-ch-ua":
          '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        signature: signature,
        Referer: "https://cnvdb.org.cn/",
      },
    });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    return data;
  } catch (error) {
    console.error("获取CNV数据失败:", error);
    throw error;
  }
}

const getCNVData = async () => {
  const data = await getCNVList();
  console.log("CNV列表:", JSON.stringify(data));
};

const getCNVDetailData = async () => {
  const data = await getCNVDetail("1965333731931074561");
  console.log("CNV详情:", JSON.stringify(data));
};

getCNVData();
getCNVDetailData();



